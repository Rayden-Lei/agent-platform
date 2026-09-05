import { Form, Input, InputNumber, Select, Typography } from 'antd'
import type { ToolRow } from '../../api'

// 工具测试弹窗的参数输入：HTTP 工具按参数声明生成输入项（不再手写 JSON）；
// 未声明参数的 HTTP 工具只能以 {} 调用，只给提示；内置工具没有声明，保留 JSON 文本框。

interface Props {
  tool: ToolRow
  values: Record<string, unknown>
  onChange: (values: Record<string, unknown>) => void
  jsonText: string
  onJsonChange: (text: string) => void
}

const BOOL_OPTIONS = [{ value: true, label: 'true' }, { value: false, label: 'false' }]

export default function ToolTestArgsForm({ tool, values, onChange, jsonText, onJsonChange }: Props) {
  if (tool.type !== 'http') {
    return (
      <Form.Item label="参数(JSON)">
        <Input.TextArea value={jsonText} onChange={(e) => onJsonChange(e.target.value)} rows={4} placeholder='{"expression":"2+3"}' />
      </Form.Item>
    )
  }
  const params = tool.config?.parameters
  const entries = Object.entries(params?.properties || {})
  if (!entries.length) {
    return <Typography.Text type="secondary">该工具未声明参数，将以空参数调用。可在编辑里补参数声明。</Typography.Text>
  }
  const required = new Set(params?.required || [])
  const set = (name: string, v: unknown) => onChange({ ...values, [name]: v })

  return (
    <>
      {entries.map(([name, prop]) => {
        const label = `${name}${prop.description ? `（${prop.description}）` : ''}`
        let control
        if (prop.type === 'boolean') control = <Select allowClear options={BOOL_OPTIONS} value={values[name] as boolean | undefined} onChange={(v) => set(name, v)} />
        else if (prop.type === 'number' || prop.type === 'integer') control = <InputNumber style={{ width: '100%' }} precision={prop.type === 'integer' ? 0 : undefined} value={values[name] as number | undefined} onChange={(v) => set(name, v ?? undefined)} />
        else if (prop.enum) control = <Select allowClear options={prop.enum.map((e) => ({ value: e, label: e }))} value={values[name] as string | undefined} onChange={(v) => set(name, v)} />
        else control = <Input value={(values[name] as string) ?? ''} onChange={(e) => set(name, e.target.value)} />
        return <Form.Item key={name} label={label} required={required.has(name)}>{control}</Form.Item>
      })}
    </>
  )
}

// 组装提交参数：未填的项不传，交给后端按声明判必填；空字符串视为未填
export function collectTestArgs(values: Record<string, unknown>): Record<string, unknown> {
  const args: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(values)) {
    if (v === undefined || v === null || v === '') continue
    args[k] = v
  }
  return args
}
