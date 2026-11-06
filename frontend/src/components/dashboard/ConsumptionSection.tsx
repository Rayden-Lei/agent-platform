import type { DailyRunStat, ModelUsageRow } from '../../api'
import ChartCard from '../charts/ChartCard'
import TrendLine from '../charts/TrendLine'
import { compactNumber, formatNumber } from '../../utils/format'

// 消耗区：按模型的 Token 排行 + 按天 Token 趋势。
//
// 2026-11-06 重做：排行原来是 G2 的横向堆叠条形图，但实际只有 2~3 个模型，
// 两根细条横在 236px 高的容器中间，上下大片空白，很难看也很难读。
// 改成手写的进度条列表：每行「模型名 + 数值 + 输入/输出双色条」，高度随内容，
// 2 个模型就是 2 行，10 个模型就是 10 行，不会再有空洞。
interface Props {
  models: ModelUsageRow[]
  daily: DailyRunStat[]
  loading: boolean
  error?: string | null
  onRetry?: () => void
}

const IN_COLOR = '#2563eb'
const OUT_COLOR = '#0d9488'

export default function ConsumptionSection({ models, daily, loading, error, onRetry }: Props) {
  const top = models.filter((m) => m.total_tokens > 0).slice(0, 6)
  const maxTotal = Math.max(1, ...top.map((m) => m.total_tokens))
  const tokenTrend = daily.map((d) => ({ date: d.date.slice(5), value: d.total_tokens }))
  const hasBars = top.length > 0

  return (
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="flex flex-col rounded-xl border border-border bg-card">
        <div className="flex items-baseline gap-2 border-b border-border px-3.5 py-2.5">
          <h3 className="m-0 text-[12.5px] font-semibold text-foreground">模型 Token 消耗</h3>
          <span className="text-[11px] text-muted-foreground">区间内 · 输入与输出</span>
        </div>
        <div className="flex flex-col gap-3 px-3.5 py-3">
          {loading && <div className="flex flex-col gap-3">{[0,1,2].map(i => <span key={i} className="block h-8 animate-pulse rounded" style={{ background: 'var(--bg-soft)' }} />)}</div>}
          {!loading && error && <span className="text-[12.5px] text-destructive">{error}</span>}
          {!loading && !error && !hasBars && <span className="py-6 text-center text-[12.5px] text-muted-foreground">区间内没有模型调用</span>}
          {!loading && !error && hasBars && top.map((m) => {
            const w = (m.total_tokens / maxTotal) * 100
            const inPct = m.total_tokens > 0 ? (m.prompt_tokens / m.total_tokens) * 100 : 0
            return (
              <div key={m.model_id ?? m.name} className="flex flex-col gap-1">
                <div className="flex items-baseline justify-between gap-3 text-[12px]">
                  <span className="truncate font-medium" style={{ color: 'var(--fg)' }} title={m.name}>{m.name}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">{formatNumber(m.total_tokens)}</span>
                </div>
                {/* 双色条：外宽表示该模型占总量的比例，内部分输入/输出 */}
                <div className="h-2 w-full overflow-hidden rounded-full" style={{ background: 'var(--bg-soft)' }}>
                  <div className="flex h-full overflow-hidden rounded-full" style={{ width: `${w}%` }}>
                    <span style={{ width: `${inPct}%`, background: IN_COLOR }} title={`输入 ${formatNumber(m.prompt_tokens)}`} />
                    <span style={{ width: `${100 - inPct}%`, background: OUT_COLOR }} title={`输出 ${formatNumber(m.completion_tokens)}`} />
                  </div>
                </div>
              </div>
            )
          })}
          {!loading && !error && hasBars && (
            <div className="flex items-center gap-3 pt-0.5 text-[11px] text-muted-foreground">
              <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full" style={{ background: IN_COLOR }} />输入</span>
              <span className="inline-flex items-center gap-1.5"><span className="size-1.5 rounded-full" style={{ background: OUT_COLOR }} />输出</span>
            </div>
          )}
        </div>
      </section>

      <ChartCard title="Token 消耗趋势" subtitle="按天合计" loading={loading} error={error} onRetry={onRetry} empty={!daily.some((d) => d.total_tokens > 0)} emptyText="区间内没有 Token 消耗" height={228}>
        <TrendLine data={tokenTrend} height={204} area yFormatter={compactNumber} />
      </ChartCard>
    </div>
  )
}
