"""LLM 调用编排：fallback + 重试退避 + 模型降级 + 竞速恢复 + 首字占位。

流程：
1. 阶段一（同模型横向）：按请求的模型 id 挑候选提供方（按 default_provider_order
   排序），逐个尝试。可重试错误（限流 429 / 5xx / 网络 / 超时）在本家按
   retry_count 退避重试，仍失败切下家；鉴权/配额等不可重试错误直接切下家；
   中途已吐内容则进错误处理（不再切换）。
2. 阶段二（模型级降级）：所有候选提供方都失败后，按该模型声明的 fallback_models
   依次降级到备选模型——每个备选模型跨所有提供它的提供方再横向尝试一轮。
3. 阶段三（竞速恢复）：session 收到降级事件后可调用 stream_deltas_race 并发
   「本家 vs 备选」两个请求，TTFB 首字快者胜出；备选先出且本家在其后
   RACE_GRACE 秒内也出首字时仍判本家胜（微小差距优先本家）。
4. 首字占位：从第一个请求计时（fallback/降级不重置），超过 first_token_stall
   秒仍无任何产出 → 先吐一帧 stall 占位（预设提示语）；后续真实内容照常到达，
   UI 换行显示、不删除占位文本。占位每请求只发一次。
5. 错误处理：记录日志 + 广播提醒 + 返回预设提示语；stall 已输出时不再重复提示。

实现说明：网络读取放在后台线程（避免阻塞主生成器），主线程经队列按需取出，
从而能让「超时占位」在流上实时插入；竞速也基于同一套后台线程机制。
"""

from __future__ import annotations

import queue
import random
import threading
import time
from collections.abc import Iterator
from dataclasses import replace

from loguru import logger

from ..bus import provide
from .config import ProviderConfig
from .errors import LLMError, NoCandidateError, is_retryable
from .message import ChatRequest
from .transport import StreamDelta, stream_chat

# 竞速判定「微小差距」窗口（秒）：备选先出首字、本家在其后该秒数内也出 → 本家胜
RACE_GRACE = 0.35

# 退避封顶（秒）与抖动幅度（比例）
BACKOFF_MAX = 2.0
BACKOFF_JITTER = 0.2

# 竞速时记录胜者的实际生效信息
RACE_TAG_HOME = "home"
RACE_TAG_FALLBACK = "fb"


class _StreamEnd:
    """后台流结束哨兵（单例比较用）。"""


_STREAM_END = _StreamEnd()


def _backoff_delay(base: float, attempt: int) -> float:
    """指数退避 + 抖动：base * 2^(attempt-1)，封顶 BACKOFF_MAX，±抖动。"""
    cap = min(BACKOFF_MAX, base * (2 ** (attempt - 1)))
    return cap * (1 + BACKOFF_JITTER * (random.random() * 2 - 1))


class _StreamRunner:
    """后台线程消费 stream_chat，供主生成器按需（可带超时）取增量。

    通话(race)模式多个 runner 可共用同一输出队列（带 tag 区分）；
    单家模式用独立私有队列。取消调用 cancel()（线程为 daemon，不会阻塞退出）。
    """

    def __init__(
        self,
        provider,
        request: ChatRequest,
        timeout: float,
        *,
        outq: queue.Queue | None = None,
        tag: str = "",
    ) -> None:
        self._q = outq if outq is not None else queue.Queue()
        self._tag = tag
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(provider, request, timeout), daemon=True
        )
        self._thread.start()

    def _run(self, provider, request, timeout) -> None:
        try:
            for delta in stream_chat(provider, request, timeout=timeout):
                if self._stop.is_set():
                    break
                self._q.put((self._tag, delta))
            self._q.put((self._tag, _STREAM_END))
        except Exception as e:  # noqa: BLE001 —— 统一经队列上抛给主线程
            if not self._stop.is_set():
                self._q.put((self._tag, e))
        finally:
            self._stop.set()

    def get(self, timeout: float | None = None):
        """取一个 (tag, item)；空队列超时抛 queue.Empty。"""
        return self._q.get(timeout=timeout)

    def cancel(self) -> None:
        """置停止位：线程在下一个增量处停下（daemon，不阻塞退出）。"""
        self._stop.set()


class LLMEngine:
    """LLM 统一出入口：多提供方 fallback + 重试退避 + 模型降级 + 竞速 + 错误处理。"""

    def __init__(
        self,
        providers: ProviderConfig,
        *,
        timeout: float,
        first_token_stall: float,
        error_message: str,
    ):
        self.providers = providers
        self.timeout = timeout            # 总体超时预算（秒）
        self.first_token_stall = first_token_stall  # 首字占位阈值（秒）
        self.error_message = error_message
        # 注册为统一服务（实例自注册，重名覆盖会记警告）
        provide("llm.stream", self.stream)        # 纯文本流式（简单场景）
        provide("llm.deltas", self.stream_deltas)  # 完整增量流式（agent loop 用）
        provide("llm.race", self.stream_deltas_race)  # 本家 vs 备选竞速（降级恢复）

    # ------------------------------------------------------------------ 服务入口

    def stream(self, request: ChatRequest) -> Iterator[str]:
        """纯文本流式：过滤掉完成事件与首字占位，只产出真实文本增量。

        适合单次问答、简单场景；需要工具调用信息/占位提醒时用 stream_deltas()。
        """
        for d in self._stream_deltas(request):
            if d.content and not d.stall:
                yield d.content

    def stream_deltas(self, request: ChatRequest) -> Iterator[StreamDelta]:
        """完整流式增量（含流结束的完成事件与首字占位）。"""
        yield from self._stream_deltas(request)

    def stream_deltas_race(
        self, home_request: ChatRequest, fallback_request: ChatRequest
    ) -> Iterator[StreamDelta]:
        """本家与备选并发竞速：TTFB 首字快者胜，微小差距（RACE_GRACE 内）优先本家。

        产出胜者的完整增量流（含完成事件，带实际 model_id / degraded / race_possible）。
        """
        yield from self._race_deltas(home_request, fallback_request)

    # ------------------------------------------------------------------ 阶段一/二

    def _stream_deltas(self, request: ChatRequest) -> Iterator[StreamDelta]:
        candidates = self.providers.candidates_for(request.model_id)
        if not candidates:
            yield from self._handle_failure(
                NoCandidateError(
                    f"没有任何提供方支持模型 {request.model_id}，请在 config/providers.toml 配置",
                    detail=request.model_id,
                )
            )
            return

        start = time.monotonic()
        stall_deadline = start + self.first_token_stall
        stall_state = {"emitted": False}

        # 阶段一：同模型横向（含本家重试退避、切下家）
        for provider in candidates:
            if self.timeout - (time.monotonic() - start) <= 0:
                logger.warning("总体超时预算已耗尽，停止切换下家")
                break
            effective = self._effective_request(request, provider)
            for attempt in range(provider.retry_count + 1):
                if attempt:
                    forward = _backoff_delay(provider.backoff_base, attempt)
                    remaining = self.timeout - (time.monotonic() - start)
                    if remaining <= forward:
                        logger.warning("总体预算不足以完成退避，停止本家重试")
                        break
                    logger.info(f"提供方 {provider.id} 退避 {forward:.2f}s 后重试")
                    time.sleep(forward)
                attempt_timeout = min(
                    provider.timeout, self.timeout - (time.monotonic() - start)
                )
                if attempt_timeout <= 0:
                    break

                emitted = False
                runner = _StreamRunner(provider, effective, attempt_timeout)
                try:
                    for delta in self._consume_attempt(runner, stall_deadline, stall_state):
                        if delta.content or delta.reasoning or delta.finish_reason:
                            emitted = True
                        if delta.finish_reason:
                            # 完成事件标记实际生效模型（未降级）
                            delta = replace(delta, model_id=request.model_id)
                        yield delta
                    return  # 该提供方完整成功，结束
                except LLMError as e:
                    e.provider_id = provider.id
                    logger.error(f"提供方 {provider.id} 失败: {e}")
                    if emitted:
                        # 已输出过内容才中断：不宜再切换，直接进错误处理
                        logger.error(f"提供方 {provider.id} 中途失败，已输出部分内容，进入错误处理")
                        yield from self._handle_failure(e, stall_emitted=stall_state["emitted"])
                        return
                    if not is_retryable(e):
                        break  # 不可重试（鉴权/配额等），切下家
                    if attempt < provider.retry_count:
                        continue  # 本家退避重试
                    break  # 重试耗尽，切下家
                finally:
                    runner.cancel()

        # 阶段二：模型级降级（所有候选提供方都失败后）
        degraded_targets = self._degraded_targets(request.model_id)
        for target in degraded_targets:
            remaining = self.timeout - (time.monotonic() - start)
            if remaining <= 0:
                break
            logger.info(f"尝试降级到备选模型 {target}")
            for provider in self.providers.candidates_for(target):
                if self.timeout - (time.monotonic() - start) <= 0:
                    break
                effective = self._effective_request(
                    replace(request, model_id=target), provider
                )
                attempt_timeout = min(
                    provider.timeout, self.timeout - (time.monotonic() - start)
                )
                if attempt_timeout <= 0:
                    break
                emitted = False
                runner = _StreamRunner(provider, effective, attempt_timeout)
                try:
                    for delta in self._consume_attempt(runner, stall_deadline, stall_state):
                        if delta.content or delta.reasoning or delta.finish_reason:
                            emitted = True
                        if delta.finish_reason:
                            delta = replace(
                                delta,
                                model_id=target,
                                degraded=True,
                                race_possible=provider.race_fallback,
                            )
                        yield delta
                    return  # 降级成功
                except LLMError as e:
                    e.provider_id = provider.id
                    logger.error(f"降级模型 {target} 在提供方 {provider.id} 失败: {e}")
                    if emitted:
                        logger.error("降级中途失败，已输出部分内容，进入错误处理")
                        yield from self._handle_failure(e, stall_emitted=stall_state["emitted"])
                        return
                    continue  # 未输出内容，试下家/下个降级目标

        logger.error("所有候选提供方与降级模型均失败或超时，进入错误处理")
        yield from self._handle_failure(
            LLMError("所有提供方均失败"), stall_emitted=stall_state["emitted"]
        )

    # ------------------------------------------------------------------ 阶段三 竞速

    def _race_deltas(
        self, home_request: ChatRequest, fallback_request: ChatRequest
    ) -> Iterator[StreamDelta]:
        """并发竞速实现：两个后台流 + 共享队列，首字（content）定胜者。"""
        home_cands = self.providers.candidates_for(home_request.model_id)
        fb_cands = self.providers.candidates_for(fallback_request.model_id)
        if not home_cands and not fb_cands:
            yield from self._handle_failure(
                NoCandidateError(
                    f"本家 {home_request.model_id} 与备选 {fallback_request.model_id} 均无提供方"
                )
            )
            return

        start = time.monotonic()
        stall_deadline = start + self.first_token_stall
        stall_state = {"emitted": False}

        entries: list[tuple[str, object]] = []
        if home_cands:
            entries.append((RACE_TAG_HOME, home_cands[0]))
        if fb_cands:
            entries.append((RACE_TAG_FALLBACK, fb_cands[0]))

        # 单边有候选：直接退化为单家串行（保持占位/降级语义）
        if len(entries) == 1:
            tag, provider = entries[0]
            base = home_request if tag == RACE_TAG_HOME else fallback_request
            degraded = tag == RACE_TAG_FALLBACK
            effective = self._effective_request(base, provider)
            attempt_timeout = min(provider.timeout, self.timeout)
            runner = _StreamRunner(provider, effective, attempt_timeout)
            try:
                for delta in self._consume_attempt(runner, stall_deadline, stall_state):
                    if delta.finish_reason:
                        delta = replace(
                            delta,
                            model_id=base.model_id,
                            degraded=degraded,
                            race_possible=provider.race_fallback,
                        )
                    yield delta
            finally:
                runner.cancel()
            return

        # 双边并发竞速
        shared: queue.Queue = queue.Queue()
        runners: dict[str, _StreamRunner] = {}
        for tag, provider in entries:
            base = home_request if tag == RACE_TAG_HOME else fallback_request
            effective = self._effective_request(base, provider)
            attempt_timeout = min(provider.timeout, self.timeout)
            runners[tag] = _StreamRunner(provider, effective, attempt_timeout, outq=shared, tag=tag)

        buffered: dict[str, list] = {RACE_TAG_HOME: [], RACE_TAG_FALLBACK: []}
        ended: dict[str, bool] = {RACE_TAG_HOME: False, RACE_TAG_FALLBACK: False}
        try:
            # ---- 决策：首个 content 出现，含「微小差距优先本家」 ----
            winner: str | None = None
            grace_until: float | None = None
            while True:
                if grace_until is not None and time.monotonic() >= grace_until:
                    if winner is None:
                        winner = RACE_TAG_FALLBACK  # 备选先到且本家未跟上
                    break
                wait = self._race_stall_wait(stall_state, stall_deadline)
                if wait is not None:
                    try:
                        tag, item = shared.get(timeout=wait)
                    except queue.Empty:
                        if not stall_state["emitted"]:
                            stall_state["emitted"] = True
                            yield StreamDelta(stall=True, content=self.error_message)
                        continue
                else:
                    tag, item = shared.get()

                if item is _STREAM_END or isinstance(item, Exception):
                    ended[tag] = True
                    if tag == RACE_TAG_HOME:
                        # 本家失败/结束：如正处 grace 窗口，直接判备选胜
                        if grace_until is not None and winner is None:
                            winner = RACE_TAG_FALLBACK
                            break
                        if ended[RACE_TAG_HOME] and ended[RACE_TAG_FALLBACK]:
                            break  # 双方都退出，交由下方整体失败
                    if winner is None and ended[RACE_TAG_HOME] and ended[RACE_TAG_FALLBACK]:
                        break
                    continue
                buffered[tag].append(item)

                if item.content and tag == RACE_TAG_HOME and winner is None and grace_until is None:
                    winner = RACE_TAG_HOME  # 本家直接先出
                    break
                if item.content and tag == RACE_TAG_FALLBACK and winner is None and grace_until is None:
                    # 备选先出：观察一段时间，本家追上则仍判本家胜
                    grace_until = time.monotonic() + RACE_GRACE
                if (
                    grace_until is not None
                    and winner is None
                    and item.content
                    and tag == RACE_TAG_HOME
                ):
                    winner = RACE_TAG_HOME  # 微小差距内本家跟上 → 本家胜
                    break

            if winner is None:
                # 双方均无产出即结束：取第一个错误，否则按失败处理
                first_err = None
                for tag in (RACE_TAG_HOME, RACE_TAG_FALLBACK):
                    for item in buffered[tag]:
                        if isinstance(item, Exception):
                            first_err = item
                            break
                    if first_err:
                        break
                if first_err is None:
                    yield from self._handle_failure(
                        LLMError("竞速双方均未产出且均已结束"),
                        stall_emitted=stall_state["emitted"],
                    )
                else:
                    yield from self._handle_failure(
                        first_err, stall_emitted=stall_state["emitted"]
                    )
                return

            # ---- 输出胜者 buffered 增量 + 实时流，直到完成事件 ----
            is_home = winner == RACE_TAG_HOME
            lose_tag = RACE_TAG_FALLBACK if is_home else RACE_TAG_HOME
            for item in buffered[winner]:
                if isinstance(item, Exception):
                    raise item
                yield self._decorate_race_delta(item, is_home, home_request, fallback_request)
            while True:
                tag, item = shared.get()
                if tag != winner:
                    continue
                if item is _STREAM_END:
                    break
                if isinstance(item, Exception):
                    raise item
                yield self._decorate_race_delta(item, is_home, home_request, fallback_request)
                if item.finish_reason:
                    break
        finally:
            for runner in runners.values():
                runner.cancel()

    def _decorate_race_delta(
        self,
        delta: StreamDelta,
        is_home: bool,
        home_request: ChatRequest,
        fallback_request: ChatRequest,
    ) -> StreamDelta:
        """竞速胜者增量：完成事件带上实际模型与是否降级。"""
        if not delta.finish_reason:
            return delta
        model_id = home_request.model_id if is_home else fallback_request.model_id
        return replace(
            delta,
            model_id=model_id,
            degraded=not is_home,
            race_possible=True,
        )

    def _race_stall_wait(self, stall_state: dict, stall_deadline: float) -> float | None:
        """竞速期间到占位时点前的等待时长；已占位/已超时返回 None（阻塞取）。"""
        if stall_state["emitted"]:
            return None
        wait = stall_deadline - time.monotonic()
        return max(wait, 0) if wait > 0 else 0

    # ------------------------------------------------------------------ 工具方法

    def _effective_request(self, request: ChatRequest, provider) -> ChatRequest:
        """未显式指定 thinking 时，按该模型配置的 thinking_default 解析。"""
        model = provider.get_model(request.model_id)
        if request.thinking is None and model is not None and model.thinking_default is not None:
            return replace(request, thinking=model.thinking_default)
        return request

    def _degraded_targets(self, model_id: str) -> list[str]:
        """收集模型降级目标：拥有该模型的提供方声明的 fallback_models 并集（去重保序）。

        候选是「模型名」而非绑定具体提供方——降级后会跨所有提供它的
        提供方重新横向尝试（不必局限于原来拥有主模型的那些）。
        """
        targets: list[str] = []
        seen: set[str] = set()
        for p in self.providers.ordered_providers():
            m = p.get_model(model_id)
            if m is None:
                continue
            for t in m.fallback_models:
                if t and t not in seen:
                    seen.add(t)
                    targets.append(t)
        return targets

    def _consume_attempt(
        self,
        runner: _StreamRunner,
        stall_deadline: float,
        stall_state: dict,
    ) -> Iterator[StreamDelta]:
        """串行消费一个后台流：到占位时点无产出先吐占位，其余增量透传。

        流正常结束返回；流错误以原类型上抛（供上层重试/切换判定）。
        """
        while True:
            if not stall_state["emitted"]:
                wait = stall_deadline - time.monotonic()
                if wait <= 0:
                    stall_state["emitted"] = True
                    yield StreamDelta(stall=True, content=self.error_message)
                    wait = None
            else:
                wait = None
            try:
                _, item = runner.get(timeout=wait)
            except queue.Empty:
                continue
            if item is _STREAM_END:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def _handle_failure(
        self, error: LLMError, *, stall_emitted: bool = False
    ) -> Iterator[StreamDelta]:
        """错误处理逻辑：记录日志、广播提醒、返回预设提示语。

        stall_emitted=True：首字占位已输出过提示语，此处不再重复发第二遍。
        """
        logger.error(f"LLM 调用失败（{error.__class__.__name__}）: {error}")
        from .notify import broadcast

        broadcast(
            "Aris LLM 连接异常",
            f"所有提供方均失败：{error}",
        )
        if not stall_emitted:
            yield StreamDelta(content=self.error_message)