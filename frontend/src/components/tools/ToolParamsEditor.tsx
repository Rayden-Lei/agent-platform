import { Button, Checkbox, Input, Select, Space, Table } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { ToolParameters, ToolPropertyType } from '../../api'

// HTTP 工具参数声明编辑器（FR-030）：以表格编辑 config.parameters（docs/03 4.2 的 JSON Schema 子集）。
// 表格行是编辑态（enum 用逗号分隔文本），对外通过 rowsFromSchema / schemaFromRows 与 schema 互转；
// 合法性由后端 422 兜底，这里只做"名称非空"这类体验性提示。

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

  const columns = [
    {
      title: '名称', dataIndex: 'name', width: 140,
      render: (v: string, r: ParamRow) => <Input value={v} placeholder="如 city" status={v.trim() ? undefined : 'error'} onChange={(e) => update(r.key, { name: e.target.value })} />,
    },
    {
      title: '类型', dataIndex: 'type', width: 100,
      // 改成非字符串类型时清掉枚举值：后端不接受非 string 的 enum
      render: (v: ToolPropertyType, r: ParamRow) => <Select value={v} options={TYPE_OPTIONS} style={{ width: '100%' }} onChange={(type) => update(r.key, { type, enumText: type === 'string' ? r.enumText : '' })} />,
    },
    {
      title: '必填', dataIndex: 'required', width: 60, align: 'center' as const,
      render: (v: boolean, r: ParamRow) => <Checkbox checked={v} onChange={(e) => update(r.key, { required: e.target.checked })} />,
    },
    {
      title: '描述', dataIndex: 'description',
      render: (v: string, r: ParamRow) => <Input value={v} placeholder="给模型看的参数含义" onChange={(e) => update(r.key, { description: e.target.value })} />,
    },
    {
      title: '枚举值', dataIndex: 'enumText', width: 150,
      render: (v: string, r: ParamRow) => <Input value={v} disabled={r.type !== 'string'} placeholder="逗号分隔，仅字符串" onChange={(e) => update(r.key, { enumText: e.target.value })} />,
    },
    {
      title: '', width: 40,
      render: (_: unknown, r: ParamRow) => <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={() => remove(r.key)} />,
    },
  ]

  return (
    <Space direction="vertical" style={{ width: '100%' }} size={8}>
      <Table rowKey="key" size="small" pagination={false} columns={columns} dataSource={value} locale={{ emptyText: '未声明参数：模型只能以空参数调用该工具' }} />
      <Button size="small" icon={<PlusOutlined />} onClick={add} disabled={value.length >= 20}>添加参数</Button>
    </Space>
  )
}
