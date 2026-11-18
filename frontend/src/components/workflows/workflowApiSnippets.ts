import type { WorkflowVariableDecl } from '../../api'
import { KEY_PLACEHOLDER, type DocRow } from '../publish/apiSnippets'

// 工作流"API 访问"页签的示例与文档（docs/15 WF-06，FR-046）：同步、异步 + 轮询、取消、续跑四段，
// 入参按线上版本的输入声明（GET /workflows/{id}/parameters）生成。全是纯函数，不发请求。
// 示例里的 Key 一律是占位符 ${KEY_PLACEHOLDER}，绝不注入真实 Key。
// 契约与 backend/app/api/v1/workflows.py 的 run / get_workflow_run / cancel_workflow_run / resume_workflow 同源。

export interface WorkflowApiTarget { id: number; name: string; published_version: number | null }

// 示例入参的取值：按声明类型给一个"看得出来要换成什么"的值，不是业务默认值
function sampleValue(type: WorkflowVariableDecl['type']): unknown {
  if (type === 'boolean') return false
  if (type === 'number' || type === 'integer') return 0
  return '示例值'
}

export function sampleInputs(variables: WorkflowVariableDecl[]): Record<string, unknown> {
  const inputs: Record<string, unknown> = {}
  for (const v of variables) inputs[v.name] = sampleValue(v.type)
  return inputs
}

// 请求体：response_mode 放在前面，调用方一眼看到是同步还是异步。
// 单行 JSON —— curl -d 里换行要额外的引号处理，示例保持可直接复制执行
export function runBody(variables: WorkflowVariableDecl[], mode: 'blocking' | 'async'): string {
  return JSON.stringify({ response_mode: mode, inputs: sampleInputs(variables) })
}

export const endpointRows = (id: number): DocRow[] => [
  { key: 'run', name: `POST /workflows/${id}/run`, desc: '运行；body 里 response_mode=blocking（默认，等到结果，超时 202 + run_id）或 async（立刻 202 + run_id）' },
  { key: 'get', name: `GET /workflows/${id}/runs/{run_id}`, desc: '查一次运行：status、output、节点执行结果；异步运行靠它轮询，只能查本 Key 发起的运行' },
  { key: 'cancel', name: `POST /workflows/${id}/runs/{run_id}/cancel`, desc: '取消运行中的运行：状态变 cancelled，引擎在下一个节点开始前停下' },
  { key: 'resume', name: `POST /workflows/${id}/runs/{run_id}/resume`, desc: '人工审核后续跑：status 为 awaiting_review 时提交 decision' },
  { key: 'parameters', name: `GET /workflows/${id}/parameters`, desc: '线上版本的输入输出声明（变量名、类型、必填、默认值、输出引用），按它填 inputs' },
]

export const ERROR_ROWS: DocRow[] = [
  { key: '400', name: '400', desc: '图校验不通过，或入参不符：未声明的键、必填变量缺值、类型不符；响应体 detail 写明原因' },
  { key: '401', name: '401', desc: 'Key 无效或已停用' },
  { key: '403', name: '403', desc: 'Key 不在本工作流的作用域内（"该 API Key 无权调用此工作流"），或工作流未发布' },
  { key: '404', name: '404', desc: '运行记录不存在，或不是本 Key 发起的（两者同一个响应，不暴露存在性）' },
  { key: '409', name: '409', desc: '取消一条已经结束（success / failed / awaiting_review）的运行' },
  { key: '429', name: '429', desc: '并发已满：同时执行的运行数达到上限，请求在创建运行记录之前就被拒绝，稍后重试' },
]

// 入参表：名字里标出必填与类型，和参数接口的声明一一对应
export function variableRows(variables: WorkflowVariableDecl[]): DocRow[] {
  return variables.map((v) => {
    const parts = [v.type, v.required ? '必填' : '可选']
    if (v.default !== null && v.default !== undefined && v.default !== '') parts.push(`默认 ${JSON.stringify(v.default)}`)
    return { key: v.name, name: v.name, desc: v.description ? `${parts.join('，')}；${v.description}` : parts.join('，') }
  })
}

const header = `-H 'Authorization: Bearer ${KEY_PLACEHOLDER}' -H 'Content-Type: application/json'`

export const blockingSnippet = (api: string, id: number, variables: WorkflowVariableDecl[]) => `# 同步运行：等到执行结束才返回；超过等待上限返回 202 + run_id，再按"异步 + 轮询"处理
curl -X POST '${api}/workflows/${id}/run' \\
  ${header} \\
  -d '${runBody(variables, 'blocking')}'`

export const asyncSnippet = (api: string, id: number, variables: WorkflowVariableDecl[]) => `# 异步运行：建完运行记录立刻返回 202 + run_id，后台继续跑
RUN_ID=$(curl -s -X POST '${api}/workflows/${id}/run' \\
  ${header} \\
  -d '${runBody(variables, 'async')}' | jq -r '.run_id')

# 轮询：running 继续等；success / failed / cancelled 是终态，awaiting_review 见"续跑"
while true; do
  STATUS=$(curl -s "${api}/workflows/${id}/runs/${'$'}RUN_ID" \\
    -H 'Authorization: Bearer ${KEY_PLACEHOLDER}' | jq -r '.status')
  echo "status: ${'$'}STATUS"
  [ "${'$'}STATUS" = "running" ] || break
  sleep 2
done`

export const cancelSnippet = (api: string, id: number) => `# 取消运行中的运行：状态变 cancelled，引擎在下一个节点开始前停下
# 已经结束的运行返回 409；重复取消返回 200 且状态不变
curl -X POST '${api}/workflows/${id}/runs/123/cancel' \\
  -H 'Authorization: Bearer ${KEY_PLACEHOLDER}'`

export const resumeSnippet = (api: string, id: number) => `# 人工审核续跑：轮询到 status 为 awaiting_review 时，用同一个 run_id 提交决策
curl -X POST '${api}/workflows/${id}/runs/123/resume' \\
  -H 'Authorization: Bearer ${KEY_PLACEHOLDER}' \\
  -H 'Content-Type: application/json' \\
  -d '{"decision": {"approved": true}}'`

const table = (rows: DocRow[], head: [string, string]) =>
  [`| ${head[0]} | ${head[1]} |`, '|---|---|', ...rows.map((r) => `| \`${r.name}\` | ${r.desc} |`)].join('\n')

// "复制对接说明"：直接发给对接方的 Markdown（Key 用占位符）
export function markdownDoc(api: string, workflow: WorkflowApiTarget, variables: WorkflowVariableDecl[]): string {
  return `# ${workflow.name} 对接说明

- Base URL：\`${api}\`
- 工作流 ID：\`${workflow.id}\`
- 鉴权：请求头 \`Authorization: Bearer ${KEY_PLACEHOLDER}\`（向管理员索取；只在服务端调用，不要放进浏览器、小程序或 App）
- Key 必须授权到这个工作流；只能查询、取消、续跑本 Key 发起的运行
- 入参按线上版本（v${workflow.published_version ?? '-'}）的输入声明；改草稿不影响这里，发布后才变

## 入参（inputs）

${variables.length ? table(variableRows(variables), ['变量', '类型与说明']) : '这个工作流没有声明输入变量，inputs 传 `{}` 即可。'}

## 端点

${table(endpointRows(workflow.id), ['端点', '说明'])}

## 同步运行

\`\`\`bash
${blockingSnippet(api, workflow.id, variables)}
\`\`\`

## 异步运行 + 轮询

\`\`\`bash
${asyncSnippet(api, workflow.id, variables)}
\`\`\`

## 取消

\`\`\`bash
${cancelSnippet(api, workflow.id)}
\`\`\`

## 人工审核续跑

\`\`\`bash
${resumeSnippet(api, workflow.id)}
\`\`\`

## 错误码

非 2xx 时响应体是 \`{"detail": "原因", "trace_id": "…"}\`：

${table(ERROR_ROWS, ['状态码', '原因'])}
`
}
