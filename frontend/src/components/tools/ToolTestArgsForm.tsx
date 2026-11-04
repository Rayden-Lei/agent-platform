import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Textarea } from '@/components/shadcn/textarea'
import type { ToolRow } from '../../api'

// 工具测试弹窗的参数输入：HTTP 工具按参数声明生成输入项（不再手写 JSON）；
// 未声明参数的 HTTP 工具只能以 {} 调用，只给提示；内置工具没有声明，保留 JSON 文本框。
// 这里只是页内片段，受控值由调用方（ToolTestModal）持有。

interface Props {
  tool: ToolRow
  values: Record<string, unknown>
  onChange: (values: Record<string, unknown>) => void
  jsonText: string
  onJsonChange: (text: string) => void
}

// 下拉里表示"不传"的哨兵值：Radix Select 不允许空字符串作为 value
const UNSET = '__unset__'

export default function ToolTestArgsForm({ tool, values, onChange, jsonText, onJsonChange }: Props) {
  if (tool.type !== 'http') {
    return (
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="tool-args-json">参数(JSON)</Label>
        <Textarea id="tool-args-json" rows={4} value={jsonText} onChange={(e) => onJsonChange(e.target.value)} placeholder='{"expression":"2+3"}' className="resize-y font-mono text-[13px]" />
      </div>
    )
  }
  const params = tool.config?.parameters
  const entries = Object.entries(params?.properties || {})
  if (!entries.length) {
    return <p className="m-0 text-[13px] text-muted-foreground">该工具未声明参数，将以空参数调用。可在编辑里补参数声明。</p>
  }
  const required = new Set(params?.required || [])
  const set = (name: string, v: unknown) => onChange({ ...values, [name]: v })

  return (
    <div className="flex flex-col gap-3">
      {entries.map(([name, prop]) => {
        const id = `tool-arg-${name}`
        const isUnset = values[name] === undefined
        let control
        if (prop.type === 'boolean') {
          control = (
            <Select value={isUnset ? UNSET : String(values[name])} onValueChange={(v) => set(name, v === UNSET ? undefined : v === 'true')}>
              <SelectTrigger id={id} className="w-full"><SelectValue placeholder="不传" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={UNSET}>不传</SelectItem>
                <SelectItem value="true">true</SelectItem>
                <SelectItem value="false">false</SelectItem>
              </SelectContent>
            </Select>
          )
        } else if (prop.type === 'number' || prop.type === 'integer') {
          control = (
            <Input
              id={id}
              type="number"
              step={prop.type === 'integer' ? 1 : 'any'}
              value={isUnset ? '' : String(values[name])}
              onChange={(e) => set(name, e.target.value === '' ? undefined : Number(e.target.value))}
            />
          )
        } else if (prop.enum) {
          control = (
            <Select value={isUnset ? UNSET : String(values[name])} onValueChange={(v) => set(name, v === UNSET ? undefined : v)}>
              <SelectTrigger id={id} className="w-full"><SelectValue placeholder="不传" /></SelectTrigger>
              <SelectContent>
                <SelectItem value={UNSET}>不传</SelectItem>
                {prop.enum.map((e) => <SelectItem key={e} value={e}>{e}</SelectItem>)}
              </SelectContent>
            </Select>
          )
        } else {
          control = <Input id={id} value={(values[name] as string) ?? ''} onChange={(e) => set(name, e.target.value)} />
        }
        return (
          <div key={name} className="flex flex-col gap-1.5">
            <Label htmlFor={id} className="flex-wrap">
              <span className="font-medium">{name}</span>
              {required.has(name) && <span className="text-destructive">*</span>}
              {prop.description && <span className="text-[12px] font-normal text-muted-foreground">（{prop.description}）</span>}
            </Label>
            {control}
          </div>
        )
      })}
    </div>
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
