import type { ReactNode } from 'react'
import { Breadcrumb, Typography } from 'antd'
import { Link } from 'react-router-dom'

// 页头：面包屑 + 标题 + 说明 + 右侧操作区。列表页与详情页共用。
export interface Crumb { label: ReactNode; to?: string }
interface Props {
  title: ReactNode
  icon?: ReactNode
  crumbs?: Crumb[]
  description?: ReactNode
  extra?: ReactNode
  tags?: ReactNode
}

export default function PageHeader({ title, icon, crumbs, description, extra, tags }: Props) {
  return (
    <div className="page-header">
      {crumbs && crumbs.length > 0 && (
        <Breadcrumb items={crumbs.map((c) => ({ title: c.to ? <Link to={c.to}>{c.label}</Link> : c.label }))} style={{ marginBottom: 6 }} />
      )}
      <div className="page-header-row">
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>{icon}{title}</h2>
            {tags}
          </div>
          {description && <Typography.Text type="secondary" style={{ fontSize: 13 }}>{description}</Typography.Text>}
        </div>
        {extra && <div style={{ flexShrink: 0 }}>{extra}</div>}
      </div>
    </div>
  )
}
