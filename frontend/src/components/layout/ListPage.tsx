import type { ReactNode } from 'react'

// 列表页骨架：把 docs/07 第 1 节的 flex 链固化 —— 根 flex:1 minHeight:0，页头 / 筛选 / 统计 / 提示 / 批量条钉死，
// 只有 fixed-table-wrapper 里的表体滚动。页面代码只剩取数 hook、列定义与弹窗编排。
interface Props {
  header: ReactNode
  filters?: ReactNode
  stats?: ReactNode
  alert?: ReactNode
  batch?: ReactNode
  children: ReactNode
}

export default function ListPage({ header, filters, stats, alert, batch, children }: Props) {
  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ flexShrink: 0 }}>{header}</div>
      {alert && <div style={{ flexShrink: 0 }}>{alert}</div>}
      {stats && <div style={{ flexShrink: 0 }}>{stats}</div>}
      {filters && <div style={{ flexShrink: 0 }}>{filters}</div>}
      {batch && <div style={{ flexShrink: 0 }}>{batch}</div>}
      <div className="fixed-table-wrapper">{children}</div>
    </div>
  )
}
