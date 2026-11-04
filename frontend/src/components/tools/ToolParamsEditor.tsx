import { Plus, Trash2 } from 'lucide-react'
import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import Button from '../ui/Button'
import type { ToolParameters, ToolPropertyType } from '../../api'

// HTTP 工具参数声明编辑器（FR-030）：以表格编辑 config.parameters（docs/03 4.2 的 JSON Schema 子集）。
// 表格行是编辑态（enum 用逗号分隔文本），对外通过 rowsFromSchema / schemaFromRows 与 schema 互转；
// 合法性由后端 422 兜底，这里只做"名称非空"这类体验性提示。
// 表格是页内小表，用原生 table（同 VariablesEditor），不引分页表格组件。

export interface ParamRow {
  key: number
  name: string
  type: ToolPropertyType
  required: boolean
  description: string
  enumText: string
}

export const TYPE_OPTIONS: { value: ToolPropertyType; label: string }[] = [
  { value: 'string', label: '字符串' },
  { value: 'number', label: '数值' },
  { value: 'integer', label: '整数' },
  { value: 'boolean', label: '布尔' },
]

let nextKey = 1

export function rowsFromSchema(schema?: ToolParameters | null): ParamRow[] {
  if (!schema?.properties) return []
  const required = new Set(schema.required || [])
  return Object.entries(schema.properties).map(([name, prop]) => ({
    key: nextKey++,
    name,
    type: prop.type,
    required: required.has(name),
    description: prop.description || '',
    enumText: (prop.enum || []).join(','),
  }))
}

export function schemaFromRows(rows: ParamRow[]): ToolParameters {
  const properties: ToolParameters['properties'] = {}
  const required: string[] = []
  for (const row of rows) {
    const name = row.name.trim()
    if (!name) continue // 空行直接忽略，不当成错误
    const enumValues = row.type === 'string' ? row.enumText.split(',').map((s) => s.trim()).filter(Boolean) : []
    properties[name] = { type: row.type, description: row.description.trim(), ...(enumValues.length ? { enum: enumValues } : {}) }
    if (row.required) required.push(name)
  }
  return { type: 'object', properties, required }
}

interface Props {
  value?: ParamRow[]
  onChange?: (rows: ParamRow[]) => void
}

export default function ToolParamsEditor({ value = [], onChange }: Props) {
  const update = (key: number, patch: Partial<ParamRow>) => onChange?.(value.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const remove = (key: number) => onChange?.(value.filter((r) => r.key !== key))
  const add = () => onChange?.([...value, { key: nextKey++, name: '', type: 'string', required: false, description: '', enumText: '' }])

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full border-collapse text-[13px]">
          <thead className="bg-secondary">
            <tr>
              <th className="w-[140px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">名称</th>
              <th className="w-[104px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">类型</th>
              <th className="w-[56px] px-2 py-1.5 text-center text-[12px] font-medium text-muted-foreground">必填</th>
              <th className="px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">描述</th>
              <th className="w-[150px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">枚举值</th>
              <th className="w-[40px]" />
            </tr>
          </thead>
          <tbody>
            {value.length === 0 && (
              <tr>
                <td colSpan={6} className="px-2 py-4 text-center text-[12.5px] text-muted-foreground">
                  未声明参数：模型只能以空参数调用该工具
                </td>
              </tr>
            )}
            {value.map((r) => (
              <tr key={r.key} className="border-t border-border">
                <td className="px-2 py-1.5">
                  <Input
                    value={r.name}
                    placeholder="如 city"
                    aria-invalid={!r.name.trim()}
                    className="h-7 text-[12.5px] aria-invalid:border-destructive"
                    onChange={(e) => update(r.key, { name: e.target.value })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <Select
                    // 改成非字符串类型时清掉枚举值：后端不接受非 string 的 enum
                    value={r.type}
                    onValueChange={(v) => update(r.key, { type: v as ToolPropertyType, enumText: v === 'string' ? r.enumText : '' })}
                  >
                    <SelectTrigger size="sm" className="w-full text-[12.5px]"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {TYPE_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </td>
                <td className="px-2 py-1.5 text-center">
                  <Checkbox checked={r.required} onCheckedChange={(v) => update(r.key, { required: v === true })} />
                </td>
                <td className="px-2 py-1.5">
                  <Input value={r.description} placeholder="给模型看的参数含义" className="h-7 text-[12.5px]" onChange={(e) => update(r.key, { description: e.target.value })} />
                </td>
                <td className="px-2 py-1.5">
                  <Input value={r.enumText} disabled={r.type !== 'string'} placeholder="逗号分隔，仅字符串" className="h-7 text-[12.5px]" onChange={(e) => update(r.key, { enumText: e.target.value })} />
                </td>
                <td className="px-1 py-1.5">
                  <Button size="sm" variant="ghost" aria-label="删除该参数" onClick={() => remove(r.key)}>
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <Button size="sm" variant="secondary" icon={<Plus />} disabled={value.length >= 20} onClick={add}>添加参数</Button>
      </div>
    </div>
  )
}
