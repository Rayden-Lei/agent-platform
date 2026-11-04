import { Suspense, type ReactNode } from 'react'
import { Skeleton } from '@/components/shadcn/skeleton'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import { CHART_HEIGHT } from './theme'

// 图表卡片：标题 + 右上角操作（区间切换等）+ 固定高度容器 + 三态（加载 / 错误 / 空）+ 懒加载兜底。
// 图表本体是 @ant-design/plots（图表库，不是 antd 组件库），这里只换外壳卡片。
interface Props {
  title: ReactNode
  extra?: ReactNode
  height?: number
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  empty?: boolean
  emptyText?: ReactNode
  children: ReactNode
}

// 加载占位：五行骨架，高度接近图表容器，图表出来时不跳版
function ChartSkeleton() {
  return (
    <div className="flex h-full flex-col justify-between gap-2">
      {[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="h-4 w-full" />)}
    </div>
  )
}

export default function ChartCard({ title, extra, height = CHART_HEIGHT, loading, error, onRetry, empty, emptyText = '暂无数据', children }: Props) {
  let body: ReactNode
  if (loading) body = <ChartSkeleton />
  else if (error) body = <ErrorState compact message={error} onRetry={onRetry} />
  else if (empty) body = <EmptyState description={emptyText} />
  else body = <Suspense fallback={<ChartSkeleton />}>{children}</Suspense>

  return (
    <section className="flex h-full flex-col rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">{title}</h3>
        {extra}
      </div>
      <div className="min-h-0 flex-1 p-3" style={{ height }}>{body}</div>
    </section>
  )
}
