import { Form, Input, InputNumber, Select } from 'antd'
import type { FormInstance } from 'antd'
import { REF_CONFIGURABLE } from './palette'

// 节点配置表单：按节点类型渲染控件；config ↔ 表单值的双向转换也放在这里，
// 编辑器只负责"点击节点回填、应用时收集"。

// 已存 config 回填到表单（args 等对象字段序列化成 JSON 文本，方便用户直接改）
export function configToFormValues(config: any) {
  const c = config || {}
  return {
    agent_id: c.agent_id, tool_name: c.tool_name, expression: c.expression, prompt: c.prompt,
    argsStr: c.args ? JSON.stringify(c.args) : '', kb_id: c.kb_id, top_k: c.top_k || 4, code: c.code,
    url: c.url, method: c.method || 'POST', count: c.count || 1, instruction: c.instruction,
    input_ref: c.input_ref, output_field: c.output_field,
  }
}

// 按节点类型把表单字段收集成 config（各类型字段不同）；JSON 文本字段先解析校验
export function collectNodeConfig(nodeType: string, vals: any): { config: any } | { error: string } {
  let config: any = {}
  if (nodeType === 'agent') { config = { agent_id: vals.agent_id }; if (vals.prompt) config.prompt = vals.prompt }
  if (nodeType === 'tool') {
    config = { tool_name: vals.tool_name }
    if (vals.argsStr) { try { config.args = JSON.parse(vals.argsStr) } catch { return { error: '参数 JSON 格式错误' } } }
  }
  if (nodeType === 'condition') config = { expression: vals.expression }
  if (nodeType === 'kb_retrieval') config = { kb_id: vals.kb_id, top_k: vals.top_k || 4 }
  if (nodeType === 'code') config = { code: vals.code || '' }
  if (nodeType === 'http') config = { url: vals.url, method: vals.method || 'POST' }
  if (nodeType === 'loop') { config = { count: vals.count || 1 }; if (vals.expression) config.expression = vals.expression }
  if (nodeType === 'human_review') config = { instruction: vals.instruction || '请审核' }
  if (REF_CONFIGURABLE.includes(nodeType)) {
    if (vals.input_ref) config.input_ref = vals.input_ref
    if (vals.output_field) config.output_field = vals.output_field
  }
  // 汇聚节点输出是 {分支末节点 id: 输出} 字典，只允许用 output_field 从中取字段
  if (nodeType === 'join' && vals.output_field) config.output_field = vals.output_field
  return { config }
}

interface Props {
  nodeType: string
  form: FormInstance
  agents: any[]
  tools: any[]
  kbs: any[]
}

export default function NodeConfigForm({ nodeType, form, agents, tools, kbs }: Props) {
  return (
    <Form form={form} layout="vertical" size="small">
      {nodeType === 'agent' && (<>
        <Form.Item name="agent_id" label="选择智能体"><Select options={agents.map((a: any) => ({ value: a.id, label: a.name }))} placeholder="选择智能体" /></Form.Item>
        <Form.Item name="prompt" label="提示词覆盖(可选)"><Input.TextArea rows={2} placeholder="留空则用默认提示词" /></Form.Item>
      </>)}
      {nodeType === 'tool' && (<>
        <Form.Item name="tool_name" label="选择工具"><Select options={tools.map((t: any) => ({ value: t.name, label: t.name }))} placeholder="选择工具" /></Form.Item>
        <Form.Item name="argsStr" label="参数(JSON,可选)"><Input.TextArea rows={2} placeholder='留空则用上游输出；HTTP 工具按参数声明校验' /></Form.Item>
      </>)}
      {nodeType === 'condition' && <Form.Item name="expression" label="条件表达式"><Input placeholder="len(input) > 5" /></Form.Item>}
      {nodeType === 'kb_retrieval' && (<>
        <Form.Item name="kb_id" label="选择知识库"><Select options={kbs.map((k: any) => ({ value: k.id, label: k.name }))} placeholder="选择知识库" /></Form.Item>
        <Form.Item name="top_k" label="召回数量 Top K"><InputNumber min={1} max={20} /></Form.Item>
      </>)}
      {nodeType === 'code' && <Form.Item name="code" label="Python 代码"><Input.TextArea rows={6} placeholder={"可用变量 input(上游输出)，把结果赋给 result"} /></Form.Item>}
      {nodeType === 'http' && (<>
        <Form.Item name="url" label="请求 URL"><Input placeholder="https://api.example.com/xxx" /></Form.Item>
        <Form.Item name="method" label="方法"><Select options={[{ value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' }]} /></Form.Item>
      </>)}
      {nodeType === 'loop' && (<>
        <Form.Item name="count" label="循环次数"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="expression" label="循环条件(可选,优先于次数)"><Input placeholder="如 len(output) < 10" /></Form.Item>
      </>)}
      {nodeType === 'human_review' && <Form.Item name="instruction" label="审核说明"><Input placeholder="请人工确认后通过" /></Form.Item>}
      {REF_CONFIGURABLE.includes(nodeType) && (<>
        <Form.Item name="input_ref" label="输入引用(可选)"><Input placeholder="留空=上游输出；如 {{input}} 或 {{node_xxx.字段}}；并行分支内不能用 {{output}}" /></Form.Item>
        <Form.Item name="output_field" label="输出字段(可选)"><Input placeholder="留空=完整输出；如 data.items" /></Form.Item>
      </>)}
      {nodeType === 'join' && (<>
        <div style={{ color: '#9ca3af', marginBottom: 8 }}>等全部分支完成后输出 {'{分支末节点 id: 输出}'}，后续节点默认以它为输入。</div>
        <Form.Item name="output_field" label="输出字段(可选)"><Input placeholder="如 node_xxx.data 从汇聚字典中取字段" /></Form.Item>
      </>)}
      {nodeType === 'parallel' && <div style={{ color: '#9ca3af' }}>从本节点拉出 2 条以上连线即为并行分支（不需要分支值）；每条分支须为线性链并汇到同一个汇聚节点。</div>}
      {(nodeType === 'start' || nodeType === 'end') && <div style={{ color: '#9ca3af' }}>该节点无需配置。</div>}
    </Form>
  )
}
