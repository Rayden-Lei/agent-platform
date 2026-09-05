import type { ReactNode } from 'react'
import { Button, Space, Tooltip } from 'antd'
import { DownloadOutlined, ReloadOutlined } from '@ant-design/icons'

// 筛选条：wrap 布局放各筛选控件，右侧固定"重置 / 刷新 / 导出"。
interface Props {
  children: ReactNode
  onReset?: () => void
  onRefresh?: () => void
  onExport?: () => void
  loading?: boolean
  extra?: ReactNode
}

export default function FilterBar({ children, onReset, onRefresh, onExport, loading, extra }: Props) {
  return (
    <div className="filter-bar">
      <Space wrap size={8}>{children}</Space>
      <Space size={4}>
        {extra}
        {onReset && <Button size="small" type="text" onClick={onReset}>重置</Button>}
        {onRefresh && <Tooltip title="刷新"><Button size="small" icon={<ReloadOutlined />} loading={loading} onClick={onRefresh} /></Tooltip>}
        {onExport && <Tooltip title="导出当前页 CSV"><Button size="small" icon={<DownloadOutlined />} onClick={onExport} /></Tooltip>}
      </Space>
    </div>
  )
}
