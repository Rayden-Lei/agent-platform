import type { DailyRunStat, ModelUsageRow } from '../../api'
import ChartCard from '../charts/ChartCard'
import StackedBar from '../charts/StackedBar'
import TrendLine from '../charts/TrendLine'
import { compactNumber } from '../../utils/format'

// 消耗区：按模型的 Token 排行（输入 / 输出堆叠）+ 按天 Token 与成本趋势。
interface Props {
  models: ModelUsageRow[]
  daily: DailyRunStat[]
  loading: boolean
  error?: string | null
  onRetry?: () => void
}

export default function ConsumptionSection({ models, daily, loading, error, onRetry }: Props) {
  const top = models.filter((m) => m.total_tokens > 0).slice(0, 6)
  const bars = top.flatMap((m) => [
    { x: m.name, value: m.prompt_tokens, series: '输入' },
    { x: m.name, value: m.completion_tokens, series: '输出' },
  ])
  const tokenTrend = daily.map((d) => ({ date: d.date.slice(5), value: d.total_tokens }))
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <ChartCard title="模型 Token 消耗" subtitle="区间内 · 输入与输出堆叠" loading={loading} error={error} onRetry={onRetry} empty={!bars.length} emptyText="区间内没有模型调用">
        <StackedBar data={bars} horizontal height={236} yFormatter={compactNumber} />
      </ChartCard>
      <ChartCard title="Token 消耗趋势" subtitle="按天合计" loading={loading} error={error} onRetry={onRetry} empty={!daily.some((d) => d.total_tokens > 0)} emptyText="区间内没有 Token 消耗">
        <TrendLine data={tokenTrend} height={236} area yFormatter={compactNumber} />
      </ChartCard>
    </div>
  )
}
