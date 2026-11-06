import type { DailyRunStat } from '../../api'
import ChartCard from '../charts/ChartCard'
import Donut from '../charts/Donut'
import TrendLine from '../charts/TrendLine'
import { STATUS_SERIES_LABEL } from '../charts/theme'
import { compactNumber } from '../../utils/format'

// 趋势区：按天运行数（按状态分序列）+ 区间内状态分布环图；区间切换 7 / 30 天。
const SERIES: (keyof DailyRunStat)[] = ['success', 'failed', 'cancelled', 'awaiting_review', 'running']
const RANGES = [7, 30]

interface Props {
  daily: DailyRunStat[]
  days: number
  onDaysChange: (days: number) => void
  loading: boolean
  error?: string | null
  onRetry?: () => void
}

export default function TrendSection({ daily, days, onDaysChange, loading, error, onRetry }: Props) {
  // 图例显示中文：序列名用状态标签，颜色由 statusSeriesColor 按标签反查
  const points = daily.flatMap((d) => SERIES.map((s) => ({ date: d.date.slice(5), value: Number(d[s] ?? 0), series: STATUS_SERIES_LABEL[s as string] ?? String(s) })))
  const totals = SERIES.map((s) => ({ key: s as string, type: STATUS_SERIES_LABEL[s as string] ?? String(s), value: daily.reduce((sum, d) => sum + Number(d[s] ?? 0), 0) })).filter((x) => x.value > 0)
  const hasData = daily.some((d) => d.total > 0)
  // 原来 antd 的 Radio.Group（optionType="button"）：两个互斥选项，用同款分段按钮表达
  const picker = (
    <div className="inline-flex items-center rounded-lg border border-border p-0.5">
      {RANGES.map((d) => (
        <button
          key={d}
          type="button"
          aria-pressed={d === days}
          onClick={() => onDaysChange(d)}
          className={d === days
            ? 'rounded-md bg-primary px-2.5 py-1 text-[12.5px] font-medium text-primary-foreground'
            : 'rounded-md px-2.5 py-1 text-[12.5px] text-muted-foreground hover:bg-accent hover:text-foreground'}
        >
          近 {d} 天
        </button>
      ))}
    </div>
  )
  return (
    /* 布局重做（2026-11-06）：原来折线占 2/3、环图占 1/3，但 7 天数据只有 7 个点，
       一条细线飘在大片空白里；环图内容小却占了整列高度。改成：
       一块卡片里「折线铺满整行 + 右侧内嵌紧凑环图」，高度共用，互不空旷。 */
    <ChartCard
      title="运行趋势"
      subtitle="按状态分序列"
      extra={picker}
      loading={loading}
      error={error}
      onRetry={onRetry}
      empty={!hasData}
      emptyText="区间内没有运行记录"
      height={300}
    >
      <div className="grid h-full gap-2 lg:grid-cols-[1fr_220px]">
        <div className="min-w-0">
          <TrendLine data={points} height={264} statusSeries yFormatter={compactNumber} />
        </div>
        <div className="hidden min-w-0 lg:block">
          <Donut data={totals} height={264} statusColors />
        </div>
      </div>
    </ChartCard>
  )
}
