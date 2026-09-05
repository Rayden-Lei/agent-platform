import { Button, Popconfirm, Space } from 'antd'

// 批量操作条：表格有选中项时出现在表格上方，列出可执行的批量动作；危险动作带二次确认。
export interface BatchAction {
  key: string
  label: string
  danger?: boolean
  confirm?: string
  run: () => void
}
interface Props {
  count: number
  onClear: () => void
  actions: BatchAction[]
  running?: boolean
}

export default function BatchActionBar({ count, onClear, actions, running }: Props) {
  if (!count) return null
  return (
    <div className="batch-bar">
      <span>已选 <b>{count}</b> 项</span>
      <Space>
        {actions.map((a) => a.confirm ? (
          <Popconfirm key={a.key} title={a.confirm} onConfirm={a.run} okButtonProps={{ danger: a.danger }}>
            <Button size="small" danger={a.danger} loading={running}>{a.label}</Button>
          </Popconfirm>
        ) : (
          <Button key={a.key} size="small" danger={a.danger} loading={running} onClick={a.run}>{a.label}</Button>
        ))}
        <Button size="small" type="text" onClick={onClear}>取消选择</Button>
      </Space>
    </div>
  )
}
