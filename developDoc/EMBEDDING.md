# Aris Embedding 方案参考：本地 Bekko vs Cloudflare BGE-M3

本文档整理 Aris 记忆系统的 Embedding 提供方两种方案的调用细节与实测数据，
服务于 `memory/` 模块的提供方抽象设计。

> 现状（2026-08-09 定案）：**按记忆层级分 provider**——
> 热记忆（实时对话、需离线）用本地 Bekko-embedding-v1-a25m（OpenVINO CPU）；
> 冷记忆（批量归档、大文本、高负荷）用云端 Cloudflare BGE-M3（免费额度内）。
> 两库维度不同（384 / 1024），各建独立 pgvector 表，互不混用。

---

## 0. 分层澄清：Embedding ≠ 检索

- **Embedding 提供方只负责「文本 → 向量」**，这是唯一职责。
- **向量检索由 PostgreSQL + pgvector 执行**（ANN 索引、相似度排序），与提供方无关。
- 因此「切云端」只切换向量生成这一层，数据库与检索链路始终在本地，架构不变。
- 不同 provider 向量维度不同（Bekko 384 / BGE-M3 1024），**一个表内只能有一种维度**；
  多 provider 并存 = 多张表（见第 4 节）。

---

## 1. 方案对比总览

| 维度 | 本地 Bekko a25m（热记忆） | Cloudflare BGE-M3（冷记忆） |
|---|---|---|
| 模型 | `hotchpotch/bekko-embedding-v1-a25m`（HF，MIT） | `@cf/baai/bge-m3` |
| 部署形态 | 本机进程内推理（OpenVINO） | 云端 REST API（Workers AI） |
| 向量维度 | 384（可 Matryoshka 截断到 256/128/64） | 1024 |
| 最大输入 | 8192 tokens | 60,000 tokens |
| 单条延迟（实测/估计） | **~10ms（中位，本机）** | 网络往返，通常几十~百 ms |
| 日常 CPU 占用（实测） | **平均 5.3%**（每 3s 一条） | 0（云端） |
| 内存占用（实测） | ~1.5 GiB 常驻 | 0 |
| 成本 | 0（自托管） | **免费额度内 $0**（见 3.4） |
| 隐私 | 数据不出本机 | 数据发往 Cloudflare |
| 多语言 | 100+ 语言 | 100+ 语言 |
| 检索质量（MMTEB） | 57.5 | ~54.6（官方文档未给，论文对比值） |
| 适合场景 | 热记忆：实时对话、频繁查询、需离线 | 冷记忆：批量归档、大文本、低频率 |

**决策依据**（AGENTS 待办「Embedding 本地实测」已闭环，2026-08-09）：

- 日常稀疏检索场景（每 3s 一条 query）实测 a25m 平均 CPU 仅 **5.3%**、峰值 6.0%，
  Aris 对话节奏远达不到连续负载，**热记忆用本地方案对主机几乎无感**。
- 连续压力测试（60s 无间隔）CPU 冲到 ~1164%（约 12 核满载），正对应冷记忆
  批量归档这类**高负荷任务**——这类交给云端，让本机 CPU 不长期高负载，延长硬件寿命。
- 单条延迟 ~10ms，对对话体感为零感知；内存 1.5 GiB 常驻可接受。

---

## 2. 本地 Bekko（已实测通过）

### 2.1 模型与获取

- Hugging Face：`hotchpotch/bekko-embedding-v1-a25m`（高质量版，已定案）
- 同系列更小的 `hotchpotch/bekko-embedding-v1-a8m`（快约 2.7 倍，质量略低，MMTEB 56.2）
- MIT 协议，官方附带 PyTorch / ONNX / OpenVINO 三种产物。

### 2.2 运行环境

- Python 3.12 实测通过（`sentence-transformers>=5` + `optimum[openvino]` +
  `openvino>=2025` + `transformers<5.1`）。
- 关键坑：OpenVINO 后端要求 `transformers<5.1`（sentence-transformers 5.x 默认拉
  transformers 5.x，需显式锁低版本）。
- 本机 x86_64 用 OpenVINO 后端（官方建议），禁用 CPU 本机无 BF16 加速时的劣化。
- **torch 不要装 CUDA 版**：`uv pip install torch` 在 Linux 默认拉 CUDA wheel
  （`+cu130`，体积大且本机无 NVIDIA GPU，纯属浪费）。CPU-only 安装方式：
  - `uv pip install torch --index-url https://download.pytorch.org/whl/cpu`
  - 或装 `torch-cpu` 包。实测 OpenVINO 后端推理不依赖 CUDA。
- 模型缓存位置：实现 memory 模块时设置 `HF_HOME` 指向项目内 `data/models/`
  （data/ 不进 git），避免散落在 `~/.cache/huggingface`。
- 以上依赖**不要加进 pyproject.toml 主依赖**（sentence-transformers/openvino 等较重，
  仅在 memory 模块需要时作为可选/独立环境安装，避免污染主 CLI 环境）。

### 2.3 调用示例

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "hotchpotch/bekko-embedding-v1-a25m",
    backend="openvino",
    device="cpu",
    model_kwargs={"file_name": "openvino/openvino_model.xml", "device": "CPU"},
)

vec = model.encode(["今天在公园看见一只橘猫"])  # -> list[float]，长度 384
```

- query 与 document **无需加任何前缀**，同一个 encode 调用即可。
- 384 维可截断：`model.encode(..., truncate_dim=256)` 减小存储与检索开销。

### 2.4 实测数据（本机 24 核 / 15 GiB，OpenVINO，OMP_NUM_THREADS=24）

| 场景 | 数值 |
|---|---|
| 批量吞吐（25 条/批） | ~324 docs/s |
| 单条延迟（中位） | 10.4 ms（P95 11.7ms） |
| 日常稀疏（每 3s 一条）CPU | 平均 5.3% |
| 连续压力 60s CPU | 平均 1164% |
| 内存峰值 | ~1.5 GiB |
| 模型首载耗时 | ~20s（之后常驻内存） |

a8m 对照：批量 ~923 docs/s，单条 4.2ms，日常 CPU 2.2%，内存 ~1.3 GiB。

---

## 3. Cloudflare BGE-M3（冷记忆专用）

### 3.1 接入方式（REST API）

- 模型 ID：`@cf/baai/bge-m3`
- 鉴权：`Authorization: Bearer <API_TOKEN>`（Cloudflare API Token，需 Workers AI 权限）
- 端点（同步）：`POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/baai/bge-m3`

```bash
curl https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/ai/run/@cf/baai/bge-m3 \
  -X POST \
  -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  -d '{
    "text": ["This is a story about an orange cloud",
             "This is a story about a llama"]
  }'
```

响应（`result.data` 为向量数组，顺序对应输入）：

```json
{
  "success": true,
  "result": {
    "data": [
      [0.012, -0.031, ...],   // 1024 维
      [-0.008, 0.023, ...]
    ]
  },
  "errors": [],
  "messages": []
}
```

参数说明：

- `text` —— 字符串或字符串数组，一次请求可传多条。
- `query` / `contexts` —— 双塔检索模式（query 对 contexts 打分），Arise 记忆检索
  若直接用 Cloudflare 可省去自算相似度，但**为保持与本地方案抽象一致，建议只用
  `text` 模式自算余弦**，让提供方抽象只暴露「文本 → 向量」。
- `truncate_inputs` —— 超长时默认报错，设 true 则截断。

### 3.2 OpenAI 兼容端点（推荐给抽象层）

Workers AI 提供 OpenAI 兼容的 `/v1/embeddings`，可直接复用 `openai` SDK：

```python
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["CLOUDFLARE_API_TOKEN"],
    base_url=(
        f"https://api.cloudflare.com/client/v4/accounts/"
        f"{os.environ['CLOUDFLARE_ACCOUNT_ID']}/ai/v1"
    ),
)

resp = client.embeddings.create(
    model="@cf/baai/bge-m3",
    input=["今天在公园看见一只橘猫"],
)
vec = resp.data[0].embedding  # list[float]，1024 维
```

- 这意味着 Aris 的 Embedding 提供方抽象可以设计成与 LLM 提供方抽象同构：
  **本地=进程内调用，云端=OpenAI 兼容 HTTP**，接口归一为 `embed(texts) -> list[vector]`。

### 3.3 批量/异步

- 大批量场景可用 Batch API（`?queueRequest=true` + 轮询 `request_id`），返回
  queued/running 状态，完成后取结果。Aris 记忆索引量级（个人项目）通常用不到，
  同步模式即可。

### 3.4 免费额度与成本

- **免费额度：每天 10,000 Neurons**（Workers Free 与 Paid 计划都有，UTC 00:00 重置）。
- embedding 每请求约 1-5 Neurons → 免费额度下每天可做几千~一万次 embedding，
  对 Aris 冷记忆归档量级（个人项目）**实际接近免费无限**。
- 超出免费额度：Free 计划直接报错停用（不扣费）；Paid 计划按 $0.011/1000 Neurons 计费。
- `@cf/baai/bge-m3` 目前在 Workers Free 计划可用（2026-07-28 变更仅移除 Kimi/GLM
  等大模型，embedding 模型不受影响）。
- 上下文窗口 60,000 tokens。
- 需要 Cloudflare 账号 + API Token，数据出本机。

---

## 4. 提供方抽象建议

**按记忆层级分 provider，两套实例并存（热/冷双库），不是二选一。**

```python
class EmbeddingProvider(Protocol):
    """文本 → 向量。返回维度固定（Bekko 384 / BGE-M3 1024）。"""

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    @property
    def dimension(self) -> int: ...
```

- **LocalBekko（热记忆）**：sentence-transformers 进程内加载，常驻内存。
  负责实时对话的记忆写入与检索，延迟 ~10ms，离线可用。
- **CloudflareBGE（冷记忆）**：OpenAI 兼容 HTTP。负责批量归档的冷数据
  建立与检索，免费额度内 $0，本机零 CPU/内存开销。
- **数据库侧**：两张 pgvector 表（`hot_memories` 384 维 / `cold_memories` 1024 维），
  各自建索引、各自检索，互不混用。检索始终在本地 PostgreSQL，与 provider 无关。
- **配置**：`memory.hot_provider = "local"`、`memory.cold_provider = "cloudflare"`，
  Cloudflare 的 account_id / api_token 放 `.env`。
- **迁移/兜底**：若本地 OpenVINO 在特定设备（如 Termux）不可用，可临时把
  热记忆也指向 cloudflare（但同一表维度固定，切换需重建该表索引）。

---

## 5. 决策记录

- **2026-08-09 定案（按记忆层级分 provider）**：
  - 热记忆 = 本地 Bekko a25m（OpenVINO CPU）。实测日常 CPU 5.3%、延迟 ~10ms、
    内存 1.5 GiB，主机几乎无感；质量（MMTEB 57.5）高，且对话需低延迟 + 离线。
  - 冷记忆 = Cloudflare BGE-M3。冷数据量大、建立/检索均为高负荷任务，
    上云省本机算力（保护硬件寿命）；免费额度内近零成本。
  - 两库维度不同（384/1024），各建独立 pgvector 表，互不混用。
- 用户已确认该方案，不再变更。
- 对应更新：AGENTS.md「已定案」、PROGRESS「已完成/待定决策」。
