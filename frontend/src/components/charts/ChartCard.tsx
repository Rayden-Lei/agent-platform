import { Suspense, type ReactNode } from 'react'
import { Skeleton } from '@/components/shadcn/skeleton'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import { CHART_HEIGHT } from './theme'

// 图表卡片外壳：标题 + 右上角操作（区间切换等）+ 固定高度容器 + 三态（加载 / 错误 / 空）+ 懒加载兜底。
// 图表本体是 @ant-design/plots（图表库，不是 antd 组件库），这里只换外壳卡片。
// 2026-11-06：标题收紧到 12.5px 并加 muted 副标题位，让多图并列时信息层级更清楚。
interface Props {
  title: ReactNode
  /** 标题旁的灰色小字说明（如「近 7 天合计」），与标题同一行 */
  subtitle?: ReactNode
  extra?: ReactNode
  height?: number
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  empty?: boolean
  emptyText?: ReactNode
  children: ReactNode
}

// 加载占位：几行骨架，高度接近图表容器，图表出来时不跳版
function ChartSkeleton() {
  return (
    <div className="flex h-full flex-col justify-between gap-2">
      {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-4 w-full" />)}
    </div>
  )
}

export default function ChartCard({ title, subtitle, extra, height = CHART_HEIGHT, loading, error, onRetry, empty, emptyText = '暂无数据', children }: Props) {
  let body: ReactNode
  if (loading) body = <ChartSkeleton />
  else if (error) body = <ErrorState compact message={error} onRetry={onRetry} />
  else if (empty) body = <EmptyState description={emptyText} />
  else body = <Suspense fallback={<ChartSkeleton />}>{children}</Suspense>

  return (
    <section className="flex h-full flex-col rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <div className="flex min-w-0 items-baseline gap-2">
          <h3 className="m-0 truncate text-[12.5px] font-semibold text-foreground">{title}</h3>
          {subtitle && <span className="truncate text-[11px] text-muted-foreground">{subtitle}</span>}
        </div>
        {extra}
      </div>
      <div className="min-h-0 flex-1 p-3" style={{ height }}>{body}</div>
    </section>
  )
}