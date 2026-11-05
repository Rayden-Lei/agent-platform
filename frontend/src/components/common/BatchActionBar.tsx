import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'

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
      <div className="flex items-center gap-2">
        {actions.map((a) => a.confirm ? (
          <InlineConfirm key={a.key} message={a.confirm} danger={a.danger} onConfirm={a.run}>
            <Button size="sm" variant={a.danger ? 'danger' : 'secondary'} disabled={running}>{a.label}</Button>
          </InlineConfirm>
        ) : (
          <Button key={a.key} size="sm" variant={a.danger ? 'danger' : 'secondary'} disabled={running} onClick={a.run}>{a.label}</Button>
        ))}
        <Button size="sm" variant="ghost" onClick={onClear}>取消选择</Button>
      </div>
    </div>
  )
}
