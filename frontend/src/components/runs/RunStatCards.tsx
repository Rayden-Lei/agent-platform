import { useState } from 'react'
import { BarChart3 } from 'lucide-react'
import type { RunsSummary } from '../../api'
import ChartCard from '../charts/ChartCard'
import StackedBar from '../charts/StackedBar'
import Button from '../ui/Button'
import { formatCost, formatNumber, formatPercent } from '../../utils/format'
import { formatDuration } from '../../utils/time'

// 运行记录统计区（2026-11-06 重做）。
//
// 之前是 8 张等大的卡片平铺（总运行/运行中/待审核/成功/失败/成功率/耗时/Token成本），
// 三个问题：
//   1. 没有主次 —— 最重要的「总共跑了多少、成败如何」和最次要的「P95 耗时」占一样大的位置；
//   2. 长数值必折行 —— 8 列时每张卡只有约 130px，「537,636 / ¥0.0231」只能断成两行，很难读；
//   3. 视觉零碎 —— 一排 8 个方块，眼睛没有落点，也不好看。
//
// 现在改成一块带层次的面板：
//   第一层 规模 + 分布条：总运行放最大字号，右边一条成败占比色带（比看两个数字更快）；
//   第二层 质量指标：成功率 / 平均耗时 / Token / 成本，四个等宽小列；
//   第三层 状态筛选：点一下即按状态过滤，当前生效的那一项高亮 —— 筛选能力保留，
//          但不再是「七张卡片都能点」那种让人不知道能点的样子。
interface Props {
  summary: RunsSummary | null
  loading: boolean
  activeStatus?: string
  onPickStatus: (status?: string) => void
}

export default function RunStatCards({ summary, loading, activeStatus, onPickStatus }: Props) {
  const [showLatency, setShowLatency] = useState(false)
  const s = summary

  const total = s?.total ?? 0
  const success = s?.success ?? 0
  const failed = s?.failed ?? 0
  // 其余 = 取消 / 运行中 / 待审核：色带上单独一段，不必让人自己相减
  const other = Math.max(0, total - success - failed)
  const pct = (n: number) => (total > 0 ? (n / total) * 100 : 0)

  const buckets = (s?.latency_buckets ?? []).map((b) => ({ x: b.label, value: b.count }))

  // 状态筛选项：与原来的「点卡片即筛选」同一套语义，只是换成一行 chip
  const chips: { key: string; label: string; count: number; danger?: boolean }[] = [
    { key: 'all', label: '全部', count: total },
    { key: 'success', label: '成功', count: success },
    { key: 'failed', label: '失败', count: failed, danger: true },
    { key: 'running', label: '运行中', count: s?.running ?? 0 },
    { key: 'awaiting_review', label: '待审核', count: s?.awaiting_review ?? 0 },
  ]

  if (loading) {
    return (
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="flex animate-pulse flex-col gap-3">
          <span className="block h-8 w-32 rounded" style={{ background: 'var(--bg-soft)' }} />
          <span className="block h-3 w-full rounded" style={{ background: 'var(--bg-soft)' }} />
          <span className="block h-10 w-full rounded" style={{ background: 'var(--bg-soft)' }} />
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="rounded-xl border border-border bg-card">
        {/* ---- 第一层：规模与成败分布 ---- */}
        <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3 px-4 pt-3.5 pb-3">
          <div className="min-w-0">
            <div className="text-[12.5px] text-muted-foreground">总运行</div>
            <div className="flex items-baseline gap-1.5">
              <span className="text-[30px] font-semibold leading-none tabular-nums" style={{ color: 'var(--fg)' }}>
                {formatNumber(total)}
              </span>
              <span className="text-[12px] text-muted-foreground">次</span>
            </div>
          </div>

          {/* 成败占比色带：一眼看出健康度，比读两个数字快 */}
          <div className="min-w-0 flex-1" style={{ minWidth: 200, maxWidth: 420 }}>
            <div className="mb-1.5 flex items-center justify-between gap-3 text-[11.5px] text-muted-foreground">
              <span>成败占比</span>
              <span className="tabular-nums">{total > 0 ? formatPercent(success / total) : '-'} 成功</span>
            </div>
            <div className="flex h-2 w-full overflow-hidden rounded-full" style={{ background: 'var(--bg-soft)' }}>
              {total > 0 && (
                <>
                  <span style={{ width: `${pct(success)}%`, background: 'var(--success)' }} title={`成功 ${success}`} />
                  <span style={{ width: `${pct(failed)}%`, background: 'var(--danger)' }} title={`失败 ${failed}`} />
                  <span style={{ width: `${pct(other)}%`, background: 'var(--border-strong)' }} title={`其他 ${other}`} />
                </>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px]">
              <Legend color="var(--success)" label="成功" value={success} />
              <Legend color="var(--danger)" label="失败" value={failed} />
              <Legend color="var(--border-strong)" label="其他" value={other} />
            </div>
          </div>
        </div>

        {/* ---- 第二层：质量与成本，四列等宽 ---- */}
        <div
          className="grid grid-cols-2 gap-px border-t border-border sm:grid-cols-4"
          style={{ background: 'var(--border)' }}
        >
          <Metric label="成功率" value={formatPercent(s?.success_rate)} hint="成功 / (成功 + 失败)，不含取消与进行中" />
          <Metric label="平均耗时" value={formatDuration(s?.avg_latency_ms)} sub={`P95 ${formatDuration(s?.p95_latency_ms)}`} hint="只统计已结束的运行；P95 = 95% 的运行快于这个值" />
          <Metric label="Token" value={formatNumber(s?.total_tokens ?? 0)} sub={`输入 ${formatNumber(s?.prompt_tokens ?? 0)} · 输出 ${formatNumber(s?.completion_tokens ?? 0)}`} />
          <Metric label="成本" value={formatCost(s?.total_cost ?? 0)} sub="各运行收尾时快照合计" />
        </div>

        {/* ---- 第三层：状态筛选 ---- */}
        <div className="flex flex-wrap items-center gap-1.5 border-t border-border px-4 py-2.5">
          <span className="mr-1 text-[12px] text-muted-foreground">按状态筛选</span>
          {chips.map((c) => {
            const active = c.key === 'all' ? !activeStatus : activeStatus === c.key
            return (
              <button
                key={c.key}
                type="button"
                onClick={() => onPickStatus(c.key === 'all' ? undefined : (active ? undefined : c.key))}
                aria-pressed={active}
                className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] transition-colors"
                style={{
                  borderColor: active ? 'var(--accent)' : 'var(--border-strong)',
                  background: active ? 'var(--accent-soft)' : 'transparent',
                  color: active ? 'var(--accent)' : 'var(--fg-muted)',
                }}
              >
                {c.label}
                <span className="tabular-nums" style={{ color: c.danger && c.count > 0 ? 'var(--danger)' : undefined }}>
                  {formatNumber(c.count)}
                </span>
              </button>
            )
          })}
          <Button size="sm" variant="ghost" className="ml-auto" icon={<BarChart3 />} onClick={() => setShowLatency(!showLatency)}>
            {showLatency ? '收起耗时分布' : '耗时分布'}
          </Button>
        </div>
      </div>

      {showLatency && (
        <ChartCard title="耗时分布（已结束的运行）" height={200} loading={loading} empty={!buckets.some((b) => b.value > 0)} emptyText="当前筛选下没有已结束的运行">
          <StackedBar data={buckets} height={176} />
        </ChartCard>
      )}
    </div>
  )
}

// 色带图例：小圆点 + 名称 + 数量
function Legend({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1.5" style={{ color: 'var(--fg-muted)' }}>
      <span className="size-1.5 rounded-full" style={{ background: color }} aria-hidden="true" />
      {label}
      <span className="tabular-nums" style={{ color: 'var(--fg)' }}>{formatNumber(value)}</span>
    </span>
  )
}

// 质量指标的一格：标签在上、主值居中、副值在下，三行等距，四格之间用 1px 分隔线
function Metric({ label, value, sub, hint }: { label: string; value: string; sub?: string; hint?: string }) {
  return (
    <div className="bg-card px-4 py-2.5" title={hint}>
      <div className="text-[11.5px] text-muted-foreground">{label}</div>
      <div className="truncate text-[17px] font-semibold leading-tight tabular-nums" style={{ color: 'var(--fg)' }}>{value}</div>
      {sub && <div className="truncate text-[11px] text-muted-foreground">{sub}</div>}
    </div>
  )
}
