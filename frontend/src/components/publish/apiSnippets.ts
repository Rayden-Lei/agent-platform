// 智能体"API 调用"卡片的对接说明（docs/15 3.7.2，PB-02）：端点、请求体、SSE 事件、错误码与示例代码，全是纯函数与常量。
// 事件与错误码与 docs/04 第 5 节、2.2 同源——改 SSE 事件或错误码时同批改这里（docs/04 第 6 节）。
// 示例里的 Key 一律是占位符 <YOUR_API_KEY>，不注入真实 Key。

export const KEY_PLACEHOLDER = '<YOUR_API_KEY>'

export interface DocRow { key: string; name: string; desc: string }

export const endpointRows = (agentId: number): DocRow[] => [
  { key: 'chat', name: `POST /agents/${agentId}/chat`, desc: '发起对话；带 conversation_id 即续聊。返回 text/event-stream（SSE）' },
  { key: 'list', name: 'GET /conversations?end_user=…', desc: '本 Key（与同一个 end_user）建的会话列表，可加 agent_id 过滤；界面里的会话看不到' },
  { key: 'messages', name: 'GET /conversations/{id}/messages?end_user=…', desc: '会话里的消息，按对话顺序' },
  { key: 'delete', name: 'DELETE /conversations/{id}?end_user=…', desc: '删除会话（含消息）' },
  { key: 'available', name: 'GET /agents/available', desc: '本 Key 能调的、已发布的智能体（id、名称、描述）' },
]

export const BODY_ROWS: DocRow[] = [
  { key: 'message', name: 'message', desc: '必填，用户消息，1～8000 字' },
  { key: 'conversation_id', name: 'conversation_id', desc: '续聊时带上 done 事件里的 conversation_id；不带即开新会话' },
  { key: 'end_user', name: 'end_user', desc: '你这边的终端用户标识（1～64 字，字母数字与 ._:@-）。同一个 Key 下不同终端用户的会话互不可见；续聊与查会话时要带同一个' },
  { key: 'client_message_id', name: 'client_message_id', desc: '幂等键（字符集同上）。续聊时超时重试带同一个：不会重复落消息、重复计费，返回首次的结果；首次仍在生成时返回 409。首轮请求（不带 conversation_id）不在幂等范围内，超时不要盲目重试，先查会话列表' },
]

export const EVENT_ROWS: DocRow[] = [
  { key: 'citations', name: 'citations', desc: 'citations: [{kb_id, chunk_id, doc_name, content, score}]。首个事件，没有知识库时为空数组' },
  { key: 'delta', name: 'delta', desc: 'content：回复文本增量，按顺序拼起来就是完整回答' },
  { key: 'tool_call', name: 'tool_call', desc: 'id, name, arguments：模型决定调用工具' },
  { key: 'tool_result', name: 'tool_result', desc: 'tool_call_id, content：工具返回（截断 200 字）' },
  { key: 'done', name: 'done', desc: 'message_id, run_id, conversation_id, usage：正常结束；client_message_id 回放首次结果时另带 replayed: true' },
  { key: 'error', name: 'error', desc: 'message：出错结束（模型不可用、熔断中、工具轮数超限等；其余为"生成失败，请稍后重试（trace: …）"）' },
]

export const ERROR_ROWS: DocRow[] = [
  { key: '401', name: '401', desc: 'Key 无效或已停用' },
  { key: '403', name: '403', desc: '"该 API Key 无权调用此智能体"、"智能体未发布"、"智能体已下线"、"API Key 不允许从该 IP 调用"' },
  { key: '404', name: '404', desc: '智能体不存在；会话不存在或不属于该智能体（含 end_user 不一致）' },
  { key: '409', name: '409', desc: '同一个 client_message_id 的首次请求仍在生成' },
  { key: '422', name: '422', desc: '请求体不合法：detail 是逐字段的数组' },
  { key: '429', name: '429', desc: '限流（带 Retry-After 秒数）或 Key 配额用尽' },
  { key: '503', name: '503', desc: '模型熔断中（带 Retry-After）；流里则以 error 事件结束' },
  { key: '500', name: '500', desc: '服务器内部错误：响应体带 trace_id，反馈时附上' },
]

export const curlSnippet = (api: string, agentId: number) => `# 发起对话（-N 关闭缓冲，边生成边输出）
curl -N -X POST '${api}/agents/${agentId}/chat' \\
  -H 'Authorization: Bearer ${KEY_PLACEHOLDER}' \\
  -H 'Content-Type: application/json' \\
  -d '{"message": "你好", "end_user": "user-001"}'

# 续聊：conversation_id 取上一次 done 事件里的值；client_message_id 让超时重试不重复计费
curl -N -X POST '${api}/agents/${agentId}/chat' \\
  -H 'Authorization: Bearer ${KEY_PLACEHOLDER}' \\
  -H 'Content-Type: application/json' \\
  -d '{"message": "再详细说说", "conversation_id": 123, "end_user": "user-001", "client_message_id": "msg-0002"}'`

export const pythonSnippet = (api: string, agentId: number) => `import json
import requests

API = "${api}"
HEADERS = {"Authorization": "Bearer ${KEY_PLACEHOLDER}"}  # 只在服务端调用，不要放进浏览器或 App


def chat(message, conversation_id=None, end_user="user-001", client_message_id=None):
    body = {"message": message, "end_user": end_user}
    if conversation_id:
        body["conversation_id"] = conversation_id
    if client_message_id:
        body["client_message_id"] = client_message_id
    with requests.post(f"{API}/agents/${agentId}/chat", headers=HEADERS, json=body, stream=True, timeout=(5, 300)) as r:
        if r.status_code >= 400:
            raise RuntimeError(f"{r.status_code} {r.json().get('detail')}")
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            if event["type"] == "delta":
                print(event["content"], end="", flush=True)
            elif event["type"] == "done":
                return event["conversation_id"]
            elif event["type"] == "error":
                raise RuntimeError(event["message"])


conversation_id = chat("你好")
chat("再详细说说", conversation_id=conversation_id, client_message_id="msg-0002")`

export const jsSnippet = (api: string, agentId: number) => `// Node 18+（自带 fetch）；只在服务端调用，不要放进浏览器或 App
const API = '${api}'
const HEADERS = { Authorization: 'Bearer ${KEY_PLACEHOLDER}', 'Content-Type': 'application/json' }

async function chat(message, { conversationId, endUser = 'user-001', clientMessageId } = {}) {
  const res = await fetch(\`\${API}/agents/${agentId}/chat\`, {
    method: 'POST', headers: HEADERS,
    body: JSON.stringify({ message, conversation_id: conversationId, end_user: endUser, client_message_id: clientMessageId }),
  })
  if (!res.ok) throw new Error(\`\${res.status} \${JSON.stringify((await res.json()).detail)}\`)
  const decoder = new TextDecoder()
  let buffer = ''
  for await (const chunk of res.body) {
    buffer += decoder.decode(chunk, { stream: true })
    let end
    while ((end = buffer.indexOf('\\n\\n')) >= 0) {
      const frame = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      if (!frame.startsWith('data: ')) continue
      const event = JSON.parse(frame.slice(6))
      if (event.type === 'delta') process.stdout.write(event.content)
      else if (event.type === 'done') return event.conversation_id
      else if (event.type === 'error') throw new Error(event.message)
    }
  }
}

const conversationId = await chat('你好')
await chat('再详细说说', { conversationId, clientMessageId: 'msg-0002' })`

const table = (rows: DocRow[], head: [string, string]) =>
  [`| ${head[0]} | ${head[1]} |`, '|---|---|', ...rows.map((r) => `| \`${r.name}\` | ${r.desc} |`)].join('\n')

// "复制对接说明"：直接发给对接方的 Markdown（Key 用占位符）
export function markdownDoc(api: string, agent: { id: number; name: string }): string {
  return `# ${agent.name} 对接说明

- Base URL：\`${api}\`
- 智能体 ID：\`${agent.id}\`
- 鉴权：请求头 \`Authorization: Bearer ${KEY_PLACEHOLDER}\`（向管理员索取；只在服务端调用，不要放进浏览器或 App）
- 每次请求消耗 1 次 Key 配额；Key 只能调用授权给它的智能体

## 端点

${table(endpointRows(agent.id), ['端点', '说明'])}

## 对话请求体（JSON）

${table(BODY_ROWS, ['字段', '说明'])}

## 示例（curl）

\`\`\`bash
${curlSnippet(api, agent.id)}
\`\`\`

## 示例（Python）

\`\`\`python
${pythonSnippet(api, agent.id)}
\`\`\`

## 返回：SSE 事件

响应是 \`text/event-stream\`，每个事件一行 \`data: <JSON>\` 加空行，按 \`type\` 区分：

${table(EVENT_ROWS, ['type', '字段与说明'])}

## 错误码

非 2xx 时响应体是 \`{"detail": "原因", "trace_id": "…"}\`：

${table(ERROR_ROWS, ['状态码', '原因'])}
`
}
