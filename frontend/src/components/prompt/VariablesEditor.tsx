import { Button, Checkbox, Input, Space, Table } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
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

  const columns = [
    { title: '名称', dataIndex: 'name', width: 150, render: (v: string, r: VarRow) => <Input value={v} placeholder="如 role" status={v.trim() ? undefined : 'error'} onChange={(e) => update(r.key, { name: e.target.value })} /> },
    { title: '描述', dataIndex: 'description', render: (v: string, r: VarRow) => <Input value={v} placeholder="给填写者看的说明" onChange={(e) => update(r.key, { description: e.target.value })} /> },
    { title: '必填', dataIndex: 'required', width: 60, align: 'center' as const, render: (v: boolean, r: VarRow) => <Checkbox checked={v} onChange={(e) => update(r.key, { required: e.target.checked })} /> },
    { title: '默认值', dataIndex: 'default', width: 150, render: (v: string, r: VarRow) => <Input value={v} placeholder="未传值时使用" onChange={(e) => update(r.key, { default: e.target.value })} /> },
    { title: '', width: 40, render: (_: unknown, r: VarRow) => <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => remove(r.key)} /> },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Table rowKey="key" size="small" pagination={false} columns={columns} dataSource={value} locale={{ emptyText: '未声明变量：内容里不能出现 {{…}} 占位符' }} />
      <Button size="small" icon={<PlusOutlined />} onClick={add} disabled={value.length >= 30}>添加变量</Button>
    </Space>
  )
}
