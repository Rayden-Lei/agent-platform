import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Trash2, Plus } from 'lucide-react'
import Button from '../ui/Button'
import type { PromptVariable } from '../../api'

// 模板变量声明编辑器（FR-028）：表格编辑 {name, description, required, default}，
// 对外通过 rowsFromVariables / variablesFromRows 与接口结构互转；名称合法性与上限由后端 422 兜底。
export interface VarRow {
  key: number
  name: string
  description: string
  required: boolean
  default: string
}

let nextKey = 1

export function rowsFromVariables(variables?: PromptVariable[]): VarRow[] {
  return (variables || []).map((v) => ({ key: nextKey++, name: v.name, description: v.description || '', required: !!v.required, default: v.default ?? '' }))
}

export function variablesFromRows(rows: VarRow[]): PromptVariable[] {
  return rows
    .filter((r) => r.name.trim()) // 空行直接忽略
    .map((r) => ({ name: r.name.trim(), description: r.description.trim(), required: r.required, default: r.default.trim() ? r.default.trim() : null }))
}

interface Props {
  value?: VarRow[]
  onChange?: (rows: VarRow[]) => void
}

export default function VariablesEditor({ value = [], onChange }: Props) {
  const update = (key: number, patch: Partial<VarRow>) => onChange?.(value.map((r) => (r.key === key ? { ...r, ...patch } : r)))
  const remove = (key: number) => onChange?.(value.filter((r) => r.key !== key))
  const add = () => onChange?.([...value, { key: nextKey++, name: '', description: '', required: false, default: '' }])

  return (
    <div className="flex flex-col gap-2">
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full border-collapse text-[13px]">
          <thead className="bg-secondary">
            <tr>
              <th className="w-[150px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">名称</th>
              <th className="px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">描述</th>
              <th className="w-[60px] px-2 py-1.5 text-center text-[12px] font-medium text-muted-foreground">必填</th>
              <th className="w-[150px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">默认值</th>
              <th className="w-[40px]" />
            </tr>
          </thead>
          <tbody>
            {value.length === 0 && (
              <tr>
                <td colSpan={5} className="px-2 py-4 text-center text-[12.5px] text-muted-foreground">
                  未声明变量：内容里不能出现 {'{{…}}'} 占位符
                </td>
              </tr>
            )}
            {value.map((r) => (
              <tr key={r.key} className="border-t border-border">
                <td className="px-2 py-1.5">
                  <Input
                    value={r.name}
                    placeholder="如 role"
                    aria-invalid={!r.name.trim()}
                    className="h-7 text-[12.5px] aria-invalid:border-destructive"
                    onChange={(e) => update(r.key, { name: e.target.value })}
                  />
                </td>
                <td className="px-2 py-1.5">
                  <Input value={r.description} placeholder="给填写者看的说明" className="h-7 text-[12.5px]" onChange={(e) => update(r.key, { description: e.target.value })} />
                </td>
                <td className="px-2 py-1.5 text-center">
                  <Checkbox checked={r.required} onCheckedChange={(v) => update(r.key, { required: v === true })} />
                </td>
                <td className="px-2 py-1.5">
                  <Input value={r.default} placeholder="未传值时使用" className="h-7 text-[12.5px]" onChange={(e) => update(r.key, { default: e.target.value })} />
                </td>
                <td className="px-1 py-1.5">
                  <Button size="sm" variant="ghost" aria-label="删除该变量" onClick={() => remove(r.key)}>
                    <Trash2 className="size-3.5 text-destructive" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <Button size="sm" variant="secondary" icon={<Plus />} disabled={value.length >= 30} onClick={add}>添加变量</Button>
      </div>
    </div>
  )
}
