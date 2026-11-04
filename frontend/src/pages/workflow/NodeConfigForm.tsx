import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { REF_CONFIGURABLE } from './palette'

// 节点配置表单：按节点类型渲染控件；config ↔ 表单值的双向转换也放在这里，
// 编辑器只负责"点击节点回填、改动时收集写回"。
// 受控：值与回传由编辑器的 values/onChange 决定（不再依赖 antd Form 的字段注册）。

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

// 按节点类型把表单字段收集成 config（各类型字段不同）；JSON 文本字段先解析校验，
// 不过时返回出错字段名，编辑器据此把该字段标红、不写回节点
export function collectNodeConfig(nodeType: string, vals: any): { config: any } | { error: string; field: string } {
  let config: any = {}
  if (nodeType === 'agent') { config = { agent_id: vals.agent_id }; if (vals.prompt) config.prompt = vals.prompt }
  if (nodeType === 'tool') {
    config = { tool_name: vals.tool_name }
    if (vals.argsStr) { try { config.args = JSON.parse(vals.argsStr) } catch { return { error: '参数 JSON 格式错误', field: 'argsStr' } } }
  }
  if (nodeType === 'condition') config = { expression: vals.expression }
  if (nodeType === 'kb_retrieval') config = { kb_id: vals.kb_id, top_k: vals.top_k || 4 }
  if (nodeType === 'code') config = { code: vals.code || '' }
  if (nodeType === 'http') config = { url: vals.url, method: vals.method || 'POST' }
  if (nodeType === 'loop') { config = { count: vals.count || 1 }; if (vals.expression) config.expression = vals.expression }
  if (nodeType === 'human_review') { config = { instruction: vals.instruction || '请审核' } }
  if (REF_CONFIGURABLE.includes(nodeType)) {
    if (vals.input_ref) config.input_ref = vals.input_ref
    if (vals.output_field) config.output_field = vals.output_field
  }
  // 汇聚节点输出是 {分支末节点 id: 输出} 字典，只允许用 output_field 从中取字段
  if (nodeType === 'join' && vals.output_field) config.output_field = vals.output_field
  return { config }
}

export type NodeFormValues = ReturnType<typeof configToFormValues>

interface Props {
  nodeType: string
  values: NodeFormValues
  onChange: (patch: Partial<NodeFormValues>) => void
  errorField?: string | null
  agents: any[]
  tools: any[]
  kbs: any[]
}

// 字段壳：标签 + 控件 + 错误（错误时标红边框）
function Field({ label, children, error }: { label: string; children: React.ReactNode; error?: boolean }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-[12.5px]">{label}</Label>
      <div className={error ? 'text-destructive [&_input]:border-destructive [&_textarea]:border-destructive' : undefined}>{children}</div>
    </div>
  )
}

function TextArea({ value, onChange, rows = 2, placeholder }: { value?: string; onChange: (v: string) => void; rows?: number; placeholder?: string }) {
  return (
    <textarea
      rows={rows}
      value={value ?? ''}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className="w-full resize-y rounded-md border border-border-strong bg-transparent px-2.5 py-1.5 font-mono text-[12.5px] leading-relaxed text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
    />
  )
}

function NumberInput({ value, onChange, min, max }: { value?: number; onChange: (v: number) => void; min: number; max: number }) {
  return (
    <Input
      type="number"
      min={min}
      max={max}
      value={value ?? ''}
      onChange={(e) => onChange(Number(e.target.value))}
      onBlur={(e) => {
        const n = Number(e.target.value)
        // 与 antd InputNumber 一致：失焦时钳到范围内
        if (!Number.isFinite(n)) { onChange(min); return }
        if (n < min) onChange(min)
        else if (n > max) onChange(max)
      }}
      className="h-8 text-[12.5px]"
    />
  )
}

function Choices({ value, options, onChange, placeholder }: { value?: string | number; options: { value: any; label: string }[]; onChange: (v: any) => void; placeholder: string }) {
  return (
    <select
      value={value ?? ''}
      onChange={(e) => {
        const raw = e.target.value
        const hit = options.find((o) => String(o.value) === raw)
        onChange(hit ? hit.value : raw)
      }}
      className="h-8 w-full rounded-md border border-border-strong bg-transparent px-2 text-[12.5px] text-foreground outline-none focus-visible:border-ring"
    >
      <option value="">{placeholder}</option>
      {options.map((o) => <option key={String(o.value)} value={String(o.value)}>{o.label}</option>)}
    </select>
  )
}

const HINT = 'text-[12px] leading-relaxed text-muted-foreground'

export default function NodeConfigForm({ nodeType, values, onChange, errorField, agents, tools, kbs }: Props) {
  const bad = (f: string) => errorField === f
  return (
    <div className="flex flex-col gap-3">
      {nodeType === 'agent' && (<>
        <Field label="选择智能体">
          <Choices value={values.agent_id} options={agents.map((a: any) => ({ value: a.id, label: a.name }))} placeholder="选择智能体" onChange={(v) => onChange({ agent_id: v })} />
        </Field>
        <Field label="提示词覆盖(可选)">
          <TextArea value={values.prompt} onChange={(v) => onChange({ prompt: v })} placeholder="留空则用默认提示词" />
        </Field>
      </>)}
      {nodeType === 'tool' && (<>
        <Field label="选择工具">
          <Choices value={values.tool_name} options={tools.map((t: any) => ({ value: t.name, label: t.name }))} placeholder="选择工具" onChange={(v) => onChange({ tool_name: v })} />
        </Field>
        <Field label="参数(JSON,可选)" error={bad('argsStr')}>
          <TextArea value={values.argsStr} onChange={(v) => onChange({ argsStr: v })} placeholder="留空则用上游输出；HTTP 工具按参数声明校验" />
        </Field>
      </>)}
      {nodeType === 'condition' && (
        <Field label="条件表达式"><Input value={values.expression ?? ''} onChange={(e) => onChange({ expression: e.target.value })} placeholder="len(input) > 5" className="h-8 text-[12.5px]" /></Field>
      )}
      {nodeType === 'kb_retrieval' && (<>
        <Field label="选择知识库">
          <Choices value={values.kb_id} options={kbs.map((k: any) => ({ value: k.id, label: k.name }))} placeholder="选择知识库" onChange={(v) => onChange({ kb_id: v })} />
        </Field>
        <Field label="召回数量 Top K"><NumberInput value={values.top_k} min={1} max={20} onChange={(v) => onChange({ top_k: v })} /></Field>
      </>)}
      {nodeType === 'code' && (
        <Field label="Python 代码">
          <TextArea rows={6} value={values.code} onChange={(v) => onChange({ code: v })} placeholder="可用变量 input(上游输出)，把结果赋给 result" />
        </Field>
      )}
      {nodeType === 'http' && (<>
        <Field label="请求 URL"><Input value={values.url ?? ''} onChange={(e) => onChange({ url: e.target.value })} placeholder="https://api.example.com/xxx" className="h-8 text-[12.5px]" /></Field>
        <Field label="方法">
          <Choices value={values.method} options={[{ value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' }]} placeholder="选择方法" onChange={(v) => onChange({ method: v })} />
        </Field>
      </>)}
      {nodeType === 'loop' && (<>
        <Field label="循环次数"><NumberInput value={values.count} min={1} max={100} onChange={(v) => onChange({ count: v })} /></Field>
        <Field label="循环条件(可选,优先于次数)"><Input value={values.expression ?? ''} onChange={(e) => onChange({ expression: e.target.value })} placeholder="如 len(output) < 10" className="h-8 text-[12.5px]" /></Field>
      </>)}
      {nodeType === 'human_review' && (
        <Field label="审核说明"><Input value={values.instruction ?? ''} onChange={(e) => onChange({ instruction: e.target.value })} placeholder="请人工确认后通过" className="h-8 text-[12.5px]" /></Field>
      )}
      {REF_CONFIGURABLE.includes(nodeType) && (<>
        <Field label="输入引用(可选)"><Input value={values.input_ref ?? ''} onChange={(e) => onChange({ input_ref: e.target.value })} placeholder="留空=上游输出；如 {{input}} 或 {{node_xxx.字段}}；并行分支内不能用 {{output}}" className="h-8 text-[12.5px]" /></Field>
        <Field label="输出字段(可选)"><Input value={values.output_field ?? ''} onChange={(e) => onChange({ output_field: e.target.value })} placeholder="留空=完整输出；如 data.items" className="h-8 text-[12.5px]" /></Field>
      </>)}
      {nodeType === 'join' && (<>
        <p className={`m-0 ${HINT}`}>等全部分支完成后输出 {'{分支末节点 id: 输出}'}，后续节点默认以它为输入。</p>
        <Field label="输出字段(可选)"><Input value={values.output_field ?? ''} onChange={(e) => onChange({ output_field: e.target.value })} placeholder="如 node_xxx.data 从汇聚字典中取字段" className="h-8 text-[12.5px]" /></Field>
      </>)}
      {nodeType === 'parallel' && <p className={`m-0 ${HINT}`}>从本节点拉出 2 条以上连线即为并行分支（不需要分支值）；每条分支须为线性链并汇到同一个汇聚节点。</p>}
      {(nodeType === 'start' || nodeType === 'end') && <p className={`m-0 ${HINT}`}>该节点无需配置。</p>}
    </div>
  )
}
