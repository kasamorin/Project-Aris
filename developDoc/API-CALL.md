# Aris API 调用参考

本文档整理 OpenAI / DeepSeek / Anthropic 三家的 HTTP API 调用细节，重点是**请求格式、消息结构、工具调用、流式与结构化输出**。主要服务于 Aris 的 LLM 提供方抽象设计。

> 三家公司中，OpenAI 与 Anthropic 文档会持续演进，本文基于 2026-08 抓取的官方文档整理。
> DeepSeek 同时兼容 OpenAI 与 Anthropic 两种请求格式，是「一套抽象两处复用」的最佳落点。

---

## 1. 全景对比

### 1.1 接口入口

| 能力 | OpenAI | DeepSeek | Anthropic |
|---|---|---|---|
| 对话端点 | `POST /v1/chat/completions`（主流）<br>`POST /v1/responses`（新推荐） | `POST /v1/chat/completions`（OpenAI 兼容） | `POST /v1/messages` |
| base_url | `https://api.openai.com/v1` | `https://api.deepseek.com`<br>Anthropic 兼容：`https://api.deepseek.com/anthropic` | `https://api.anthropic.com` |
| 鉴权方式 | `Authorization: Bearer <key>` | 同 OpenAI | Header `x-api-key: <key>`<br>+ `anthropic-version: 2023-06-01` |
| 主推模型（2026-08） | gpt-5.6 sol/terra/luna | deepseek-v4 flash/pro | Opus 5 / Sonnet 5 / Haiku 4.5 / Fable 5 |

### 1.2 会话模型

| 维度 | OpenAI / DeepSeek | Anthropic |
|---|---|---|
| 有状态/无状态 | 无状态，每次传全量 `messages` | 无状态，每次传全量 `messages` |
| 系统提示 | `messages` 数组里的 `system`（或 `developer`）角色 | 顶层 `system` 字段（不占 messages 位置） |
| 多轮续接 | 手动把前次 assistant 消息追加进 `messages` | 同样手动追加 |
| 响应文本位置 | `choices[0].message.content` | `content[]` 块数组（`type:"text"`） |

三家都是**无状态、手动维护全量历史**，这是 Aris 采用「每次请求拼全量 messages」方案的基础。

### 1.3 工具调用结构差异（最容易踩坑）

| 环节 | OpenAI / DeepSeek | Anthropic |
|---|---|---|
| 工具定义 | `{"type":"function","function":{name,description,parameters}}` | `{name, description, input_schema}`（无 type、无外层） |
| 参数 schema 字段名 | `parameters` | `input_schema` |
| 模型返回 | `message.tool_calls[]`，每项 `{id, function:{name, arguments}}` | `content[]` 里的 `tool_use` 块 `{id, name, input}` |
| 参数是字符串还是对象 | JSON **字符串**（`arguments`，需 `json.loads`） | 直接对象（`input`） |
| 结果回传 | `{"role":"tool","tool_call_id":id,"content":...}` | assistant 消息原样 + `user` 消息内 `{"type":"tool_result","tool_use_id":id,"content":...}` |
| 是否调用了工具 | `finish_reason == "tool_calls"` | `stop_reason == "tool_use"` |

---

## 2. OpenAI Chat Completions（格式参考：候选之一）

> DeepSeek 原生兼容的就是这个格式（Aris 的 LLM 提供方式与提供方选型未定，
> 此处仅作格式参考）。以下字段对兼容该格式的各家通用。

### 2.1 基础请求

```http
POST https://api.deepseek.com/chat/completions
Content-Type: application/json
Authorization: Bearer $API_KEY
```

```json
{
  "model": "deepseek-v4-flash",
  "messages": [
    {"role": "system", "content": "你是 Aris，一个拟人 AI。"},
    {"role": "user", "content": "今天过得怎么样？"}
  ],
  "stream": false
}
```

**必填字段**：`model`、`messages`。

**messages 角色**：
- `system` —— 系统级指令（模型规则、人格设定）。OpenAI o 系列之后建议改用 `developer`。
- `developer` —— 开发者指令，优先级高于 system（OpenAI 新模型用）。
- `user` —— 用户消息。
- `assistant` —— 模型之前的回复（多轮续接用）。
- `tool` —— 工具执行结果，必须带 `tool_call_id`。

**常用可选参数**：
- `temperature` (0~2) 采样随机性；`top_p` 核采样（一般二选一）
- `max_tokens` / `max_completion_tokens` —— 后者为新一代推荐，包含 reasoning tokens
- `stop` —— 最多 4 个停止序列
- `frequency_penalty` / `presence_penalty`（-2~2）
- `stream` —— true 时返回 SSE 流
- `tools` / `tool_choice` —— 工具调用
- `response_format` —— 结构化输出
- `user` —— 用户标识（缓存命中/滥用检测），新版被 `safety_identifier` 和 `prompt_cache_key` 取代
- `seed` —— 尽力确定性采样（Beta）
- `n` —— 生成几个候选（默认 1，会多倍计费）

### 2.2 响应格式

```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "model": "deepseek-v4-flash",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "我还不错，谢谢关心！",
        "reasoning_content": "（思考链，DeepSeek 思考模式下存在）",
        "tool_calls": null
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 12,
    "total_tokens": 32
  }
}
```

**取文本**：`choices[0].message.content`（可能为 null，比如纯工具调用轮）。

**finish_reason 取值**：`stop`（正常结束）/ `length`（触达 max_tokens）/ `tool_calls`（需要执行工具）/ `content_filter`（内容被过滤）。

**DeepSeek 特有**：思考模式下多一个 `message.reasoning_content` 字段（思维链），与 `content` 同级。

### 2.3 多轮对话

每轮把模型的 assistant 消息原样追加回 messages 再发：

```python
messages = [{"role": "system", "content": "你是 Aris"}]
while True:
    user_input = input("你: ")
    messages.append({"role": "user", "content": user_input})
    resp = client.chat.completions.create(model=..., messages=messages)
    assistant_msg = resp.choices[0].message
    print("Aris:", assistant_msg.content)
    messages.append(assistant_msg)   # 关键：把上轮 assistant 消息放回历史
```

**DeepSeek 思考模式注意**：无工具调用时，`reasoning_content` 无需回传（会被忽略）；**一旦请求带了 `tools`，所有后续请求必须完整回传 `reasoning_content`**，否则返回 400。直接用 `messages.append(assistant_msg)` 即可满足（assistant 消息对象自带全部字段）。

### 2.4 工具调用

#### 定义工具

```json
{
  "model": "deepseek-v4-flash",
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "查询指定地点的天气",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "城市名，如 杭州"
            },
            "units": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"],
              "description": "温度单位"
            }
          },
          "required": ["location"],
          "additionalProperties": false
        }
      }
    }
  ],
  "tool_choice": "auto"
}
```

- `strict: true`（OpenAI）保证参数严格符合 schema，要求每个 object 设 `additionalProperties: false` 且所有字段进 `required`。
- 工具名：a-z/A-Z/0-9/下划线/连字符，最长 64。
- 工具定义会注入上下文，计入 input tokens（工具越多越贵）。

**tool_choice 取值**：
- `"none"` —— 禁止调用工具
- `"auto"` —— 默认，模型自己决定
- `"required"` —— 至少调一个
- `{"type":"function","function":{"name":"get_weather"}}` —— 强制调指定工具

#### 收到工具调用

```json
{
  "choices": [{
    "message": {
      "role": "assistant",
      "content": null,
      "tool_calls": [
        {
          "id": "call_001",
          "type": "function",
          "function": {
            "name": "get_weather",
            "arguments": "{\"location\": \"杭州\", \"units\": \"celsius\"}"
          }
        }
      ]
    },
    "finish_reason": "tool_calls"
  }]
}
```

注意：`arguments` 是 **JSON 字符串**，必须 `json.loads` 解析。`tool_calls` 可能是数组（并行调用）。

#### 回传工具结果（完整一轮）

```python
messages += [assistant_msg]                     # 上轮 assistant 消息（含 tool_calls）入历史
for tc in assistant_msg.tool_calls:
    result = execute(tc.function.name, json.loads(tc.function.arguments))
    messages.append({
        "role": "tool",
        "tool_call_id": tc.id,
        "content": json.dumps(result, ensure_ascii=False),
    })

resp2 = client.chat.completions.create(model=..., messages=messages, tools=tools)
print(resp2.choices[0].message.content)
```

工具可能连续多轮：只要 `finish_reason == "tool_calls"` 就继续执行并回传，直到 `content` 非空。

### 2.5 流式输出

`stream: true` 时返回 SSE，逐 chunk 增量：

```python
stream = client.chat.completions.create(model=..., messages=..., tools=tools, stream=True)

content = ""
tool_calls = {}          # index -> {id,name,arguments}
reasoning = ""

for chunk in stream:
    if not chunk.choices:      # 最后一个 usage chunk 可能无 choices
        continue
    delta = chunk.choices[0].delta
    if delta.content:
        content += delta.content
    if delta.reasoning_content:            # DeepSeek 思考链增量
        reasoning += delta.reasoning_content
    if delta.tool_calls:                   # 工具参数分片，需按 index 拼装
        for tc in delta.tool_calls:
            slot = tool_calls.setdefault(tc.index, {"id": tc.id, "name": tc.function.name, "arguments": ""})
            if tc.function and tc.function.arguments:
                slot["arguments"] += tc.function.arguments
```

- 每个 chunk 的 `delta.tool_calls` 里 `arguments` 是**增量片段**，必须按 `index` 累积拼接。
- 流以 `data: [DONE]` 结尾（Anthropic 的 Responses 无此标记，但 Chat Completions 有）。
- 想拿最终 token 用量：加 `stream_options: {"include_usage": true}`，结束前会有一个 `choices` 为空的 usage chunk。
- 流中断可能拿不到最终 usage。

### 2.6 结构化输出

#### Structured Outputs（推荐，强 schema 保证）

```json
{
  "model": "deepseek-v4-flash",
  "messages": [{"role": "user", "content": "把这句话里的日期抽出来"}],
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "date_extraction",
      "strict": true,
      "schema": {
        "type": "object",
        "properties": {
          "date": {"type": "string", "description": "ISO 格式日期"},
          "event": {"type": "string"}
        },
        "required": ["date", "event"],
        "additionalProperties": false
      }
    }
  }
}
```

约束：`strict: true` 时所有 object 需 `additionalProperties: false`，所有字段进 `required`。可选字段用 `"type": ["string","null"]` 表达。

#### JSON mode（旧式，只保证合法 JSON）

```json
{"response_format": {"type": "json_object"}}
```

注意：JSON mode 仍需在 prompt 里让模型输出 JSON。DeepSeek 也有自己的 `response_format: {"type": "json_object"}` 支持。

#### 安全拒绝

模型拒绝回答时，响应里可能出现 `refusal` 字段（OpenAI），或 `choices[0].message.refusal`。代码里要处理「拒绝」与「输出不符合 schema」两种异常，不要假设 schema 一定被满足。

### 2.7 会话状态管理（Chat Completions）

只有一种：**手动维护 messages 全量历史**。无 `previous_response_id`、无 conversation 对象。

### 2.8 错误响应（看懂报错）

请求失败时返回非 2xx 状态码，body 是 JSON。OpenAI / DeepSeek 通用结构：

```json
{
  "error": {
    "message": "Incorrect API key provided: sk-***...",
    "type": "invalid_request_error",
    "param": null,
    "code": "invalid_api_key"
  }
}
```

**看懂方法**：
- `message` —— 人类可读的错误描述（中文服务商可能直接给中文）。
- `code` —— 机器可读错误码（如 `invalid_api_key` / `insufficient_quota` / `rate_limit_exceeded` / `context_length_exceeded`）。
- `type` —— 错误大类，常见：
  - `invalid_request_error` —— 请求参数不合法（400），查 body 拼写、字段名、模型名
  - `authentication_error` —— 鉴权失败（401），查 key
  - `insufficient_quota` / `permission_error` —— 额度/权限问题（403）
  - `rate_limit_error` —— 限速（429），等服务端重试
  - `server_error` —— 服务端错误（5xx），稍后重试

**常见状态码**：

| 状态码 | 含义 | 常见原因 |
|---|---|---|
| 400 | 请求无效 | 参数格式错、模型名错、超上下文、DeepSeek 带 tools 未回传 reasoning_content |
| 401 | 未授权 | API key 错误或缺失 |
| 403 | 禁止访问 | 额度用完、地区限制 |
| 404 | 不存在 | 端点或模型名拼错 |
| 429 | 请求过多 | 触达并发/速率限制（DeepSeek 响应头带重试时间） |
| 500/502/503 | 服务端问题 | 提供方故障，重试即可 |

**DeepSeek 特有**：错误码文档见官网「错误码」页；带 `tools` 请求若缺少 `reasoning_content` 回传，返回 400。

### 2.9 完整可运行示例

#### curl（基础文本请求）

```bash
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [
      {"role": "system", "content": "你是 Aris，一个拟人 AI，说话简洁自然。"},
      {"role": "user", "content": "用一句话介绍你自己。"}
    ],
    "stream": false
  }'
```

#### curl（工具调用）

```bash
curl https://api.deepseek.com/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
  -d '{
    "model": "deepseek-v4-flash",
    "messages": [
      {"role": "system", "content": "你是 Aris。查天气时调用工具。"},
      {"role": "user", "content": "杭州天气怎么样？"}
    ],
    "tools": [
      {
        "type": "function",
        "function": {
          "name": "get_weather",
          "description": "查询指定地点的天气",
          "parameters": {
            "type": "object",
            "properties": {
              "location": {"type": "string", "description": "城市名"}
            },
            "required": ["location"],
            "additionalProperties": false
          }
        }
      }
    ],
    "tool_choice": "auto"
  }'
```

#### Python（OpenAI SDK，完整流程含工具循环）

```python
import json
import os

from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DEEPSEEK_API_KEY"],
    base_url="https://api.deepseek.com",
)

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定地点的天气",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "城市名，如 杭州"},
                },
                "required": ["location"],
                "additionalProperties": False,
            },
        },
    }
]

def execute_tool(name: str, args: dict) -> str:
    """模拟工具执行，实际项目里换成真实函数。"""
    if name == "get_weather":
        return json.dumps({"location": args["location"], "temp": 24, "desc": "多云"})
    raise ValueError(f"未知工具: {name}")

messages = [
    {"role": "system", "content": "你是 Aris，一个拟人 AI。"},
    {"role": "user", "content": "杭州天气怎么样？"},
]

for _ in range(10):  # 防死循环上限
    resp = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=messages,
        tools=tools,
    )
    msg = resp.choices[0].message
    messages.append(msg)  # 必须：assistant 消息（含 reasoning_content/tool_calls）入历史

    if resp.choices[0].finish_reason == "tool_calls":
        for tc in msg.tool_calls:
            result = execute_tool(tc.function.name, json.loads(tc.function.arguments))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
        continue  # 继续循环直到模型给出最终回答

    print("Aris:", msg.content)
    break
```

**照抄要点**：`api_key` 用你的 DeepSeek key，`base_url` 固定 `https://api.deepseek.com`；工具循环里 `messages.append(msg)` 这行不能省（DeepSeek 带 tools 时缺 reasoning_content 会 400）。

---

## 3. OpenAI Responses API（备用/将来）

> OpenAI 官方新推荐，DeepSeek 也支持（仅 deepseek-v4-flash）。若未来切 OpenAI 原生可考虑。功能更丰富，但字段名与 Chat Completions 差异大。

### 3.1 基础请求

```http
POST https://api.deepseek.com/v1/responses   # 或 https://api.openai.com/v1/responses
```

```json
{
  "model": "gpt-5.6",
  "input": "写个关于独角兽的睡前故事",
  "instructions": "用中文回答，语气温柔。"
}
```

- `input` —— 字符串或消息数组（无 role 的平铺格式，或 `{role, content}`）
- `instructions` —— 顶层系统指令，优先级高于 input 里的 developer 消息，等价于首条 developer 消息
- `input` 与 `instructions` 至少传一个

### 3.2 响应

```json
{
  "id": "resp_xxx",
  "output": [
    {
      "id": "msg_xxx",
      "type": "message",
      "role": "assistant",
      "content": [{"type": "output_text", "text": "...", "annotations": []}]
    }
  ],
  "status": "completed"
}
```

**关键**：文本在 `output` 数组里，但 `output` 可能含 tool call、reasoning 等多项，**不要假设文本在 `output[0].content[0]`**。SDK 提供 `response.output_text` 便捷聚合。

### 3.3 工具调用（Responses 版）

- 工具定义**无 `function` 外层**：`{"type":"function","name":"get_weather","description":"...","parameters":{...},"strict":true}`
- 模型返回：`output[]` 里 `{"type":"function_call","call_id":"call_xxx","name":...,"arguments":"{...}"}`
- 回传：`{"type":"function_call_output","call_id":"call_xxx","output":"..."}`，追加到 input
- 流式事件：`response.output_item.added` → `response.function_call_arguments.delta`（拼 arguments）→ `response.function_call_arguments.done`
- 流式以 `response.completed` 结束，**无 `data: [DONE]`**

### 3.4 会话状态

- `previous_response_id` —— 链式续接上一条响应
- Conversations API —— 持久化会话对象
- 手动全量回传 output（最通用，DeepSeek 兼容）
- 响应默认存 30 天，`store: false` 关闭

### 3.5 DeepSeek 兼容性注意

- 仅 `deepseek-v4-flash` 支持 Responses API（pro 暂不支持，预计 2026-08 初支持）
- 不支持的参数**静默忽略**不报错，现有客户端无需修改即可接入
- `previous_response_id`、`store`、`conversation`、`background` 等不支持
- 无状态：输入超上下文返回 400

---

## 4. DeepSeek 特有能力

### 4.1 思考模式

- 默认开启，`extra_body={"thinking":{"type":"enabled"}}`（OpenAI SDK 里 thinking 参数要放 extra_body）
- `reasoning_effort`: `low` / `high` / `max`（OpenAI 格式）
- 思考模式不支持 `temperature` / `top_p` / `presence_penalty` / `frequency_penalty`（设置不报错但不生效）
- 思维链在 `message.reasoning_content`（非流式）或 `delta.reasoning_content`（流式）
- **多轮回传规则**见 2.3 节：带 tools 时必须回传 reasoning_content

### 4.2 Anthropic API 兼容

base_url 换 `https://api.deepseek.com/anthropic` 即可用 Anthropic 格式调用 DeepSeek 模型：
- `claude-opus*` 模型名 → 映射 deepseek-v4-pro
- `claude-haiku*` / `claude-sonnet*` → 映射 deepseek-v4-flash
- 不支持的模型名自动映射到 deepseek-v4-flash
- `temperature` 范围 0.0~2.0，`thinking` 支持（`budget_tokens` 忽略）
- 工具结果 `tool_result` 支持；图片、document、MCP tool 不支持

### 4.3 价格（2026-08，每百万 tokens，人民币）

| 模型 | 输入(未命中缓存) | 输入(缓存命中) | 输出 | 上下文/输出上限 |
|---|---|---|---|---|
| deepseek-v4-flash | ¥1 | ¥0.02 | ¥2 | 1M / 384K |
| deepseek-v4-pro | ¥3 | ¥0.025 | ¥6 | 1M / 384K |

> 官方预告近期整体上调价格、涨幅较大，需关注更新。

---

## 5. Anthropic Messages API（备用）

> 现状用不上，留着万一将来切换 Claude 原生。

### 5.1 基础请求

```http
POST https://api.anthropic.com/v1/messages
x-api-key: $ANTHROPIC_API_KEY
anthropic-version: 2023-06-01
```

```json
{
  "model": "claude-opus-5",
  "max_tokens": 1024,
  "system": "你是 Aris，一个拟人 AI。",
  "messages": [
    {"role": "user", "content": "今天过得怎么样？"}
  ]
}
```

- `max_tokens` **必填**
- `system` 顶层字段，可传字符串或内容块数组
- 4.7 及以后模型：`temperature`/`top_p`/`top_k` 已废弃，传非默认值报 400

### 5.2 响应

```json
{
  "id": "msg_xxx",
  "type": "message",
  "role": "assistant",
  "content": [
    {"type": "text", "text": "我还不错，谢谢关心！"}
  ],
  "stop_reason": "end_turn",
  "usage": {"input_tokens": 12, "output_tokens": 6}
}
```

- `content` 是**内容块数组**，取文本要遍历找 `type == "text"`
- `stop_reason`: `end_turn` / `max_tokens` / `stop_sequence` / `tool_use` / `refusal`

### 5.3 工具调用

定义（无 type、无外层、schema 字段叫 `input_schema`）：

```json
{
  "model": "claude-opus-5",
  "max_tokens": 1024,
  "tools": [
    {
      "name": "get_weather",
      "description": "查询指定地点天气",
      "input_schema": {
        "type": "object",
        "properties": {"location": {"type": "string"}},
        "required": ["location"]
      }
    }
  ],
  "tool_choice": {"type": "auto", "disable_parallel_tool_use": true}
}
```

模型返回 `stop_reason: "tool_use"`，content 里有：

```json
{
  "type": "tool_use",
  "id": "toolu_01xxx",
  "name": "get_weather",
  "input": {"location": "杭州"}
}
```

`input` 直接是对象（无需 json.loads）。

回传结果——**assistant 消息原样入历史**，再追加 user 消息：

```python
messages.append({"role": "assistant", "content": response.content})   # 原样！
messages.append({
    "role": "user",
    "content": [
        {"type": "tool_result", "tool_use_id": tool_use.id, "content": "15 度，多云"}
    ]
})
resp2 = client.messages.create(model=..., messages=messages, tools=tools)
```

并行调用默认开启（`disable_parallel_tool_use` 可关）；`tool_choice` 可强制 `{"type":"tool","name":...}`。

### 5.4 流式

`stream: true` SSE 事件流，典型事件：
- `message_start`
- `content_block_start`
- `content_block_delta` —— `text_delta` 拼文本；`input_json_delta` 拼工具参数（`partial_json`）
- `content_block_stop` / `message_delta` / `message_stop`

### 5.5 服务端工具（无需应用侧执行）

`web_search`、`web_fetch`、`code_execution`、`tool_search` 在 Anthropic 基础设施上执行，直接返回结果。另有 Anthropic 预定义 schema 的客户端工具：bash、text_editor、memory、computer use。

---

## 6. 对 Aris 提供方抽象的设计建议

1. **候选方案一：抽象层基于 OpenAI Chat Completions 格式**（字段最成熟，DeepSeek 原生兼容）。
   最终选哪种格式（v1/chat vs v1/responses vs Anthropic 等）未定，见 `../AGENTS.md`。
2. 统一归一化三层差异：
   - 工具定义 → 内部统一 `{name, description, parameters}`
   - 模型返回 → 统一成 `{call_id, name, arguments(dict)}`
   - 结果回传 → 统一成「内部消息」再按提供方翻译成 `role:"tool"` 或 `tool_result`
3. 会话维护用「手动拼全量 messages」，三家都支持，无需状态存储。
4. 流式事件按提供方适配：OpenAI/DeepSeek 拼 `delta.content` + `delta.tool_calls`（按 index）；Anthropic 拼 `content_block_delta`。
5. 未来若接 OpenAI Responses，只需新增一个「归一化层」把 Responses 的 output 数组转成内部消息格式。
