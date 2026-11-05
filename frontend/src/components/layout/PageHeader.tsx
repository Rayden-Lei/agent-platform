import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

// 页头：面包屑 + 标题 + 说明 + 右侧操作区。列表页与详情页共用。
//
// 移动端（2026-11-06 改）：操作区原来与标题同一行且 shrink-0，按钮一多就把标题压到几十像素宽
// （技能页实测标题只剩 97px，智能体详情页的操作区直接顶出屏幕 120px）。窄屏改为上下两段：
// 标题独占一行，操作区在下方横向排列、放不下时换行 —— 按钮不会消失，标题也不会被压扁。
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
        <nav aria-label="面包屑" className="mb-1.5 flex items-center gap-1 text-[12.5px] text-muted-foreground">
          {crumbs.map((c, i) => (
            <span key={i} className="inline-flex items-center gap-1">
              {i > 0 && <ChevronRight className="size-3 opacity-60" aria-hidden="true" />}
              {c.to ? <Link to={c.to} className="hover:text-foreground hover:underline">{c.label}</Link> : c.label}
            </span>
          ))}
        </nav>
      )}
      <div className="page-header-row">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h2 className="m-0 flex items-center gap-2 text-[20px] font-semibold">
              {icon && <span className="flex items-center text-muted-foreground [&_svg]:size-[19px]">{icon}</span>}
              {title}
            </h2>
            {tags}
          </div>
          {description && <p className="m-0 mt-1 text-[14px] leading-relaxed text-muted-foreground">{description}</p>}
        </div>
        {extra && <div className="page-header-extra">{extra}</div>}
      </div>
    </div>
  )
}
