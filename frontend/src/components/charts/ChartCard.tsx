import { Suspense, type ReactNode } from 'react'
import { Card, Skeleton } from 'antd'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import { CHART_HEIGHT } from './theme'

// 图表卡片：标题 + 右上角操作（区间切换等）+ 固定高度容器 + 三态（加载 / 错误 / 空）+ 懒加载兜底。
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

export default function ChartCard({ title, extra, height = CHART_HEIGHT, loading, error, onRetry, empty, emptyText = '暂无数据', children }: Props) {
  let body: ReactNode
  if (loading) body = <Skeleton active paragraph={{ rows: 5 }} />
  else if (error) body = <ErrorState compact message={error} onRetry={onRetry} />
  else if (empty) body = <EmptyState description={emptyText} />
  else body = <Suspense fallback={<Skeleton active paragraph={{ rows: 5 }} />}>{children}</Suspense>
  return (
    <Card size="small" title={title} extra={extra} className="chart-card" styles={{ body: { height, padding: 12 } }}>
      {body}
    </Card>
  )
}
