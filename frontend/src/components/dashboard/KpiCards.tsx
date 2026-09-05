import type { DailyRunStat, RunMetrics } from '../../api'
import StatCards from '../layout/StatCards'
import { deltaRatio, formatCost, formatNumber, formatPercent } from '../../utils/format'
import { formatDuration } from '../../utils/time'

// 今日核心指标：运行数 / 成功率 / 失败 / Token / 成本 / 平均耗时，带与昨日的环比（来自按天序列的最后两天）。
interface Props {
  today: RunMetrics | null
  daily: DailyRunStat[]
  loading: boolean
  onGo: (path: string) => void
}

export default function KpiCards({ today, daily, loading, onGo }: Props) {
  const yesterday = daily.length >= 2 ? daily[daily.length - 2] : null
  const delta = (key: keyof RunMetrics) => (today && yesterday ? deltaRatio(Number(today[key] ?? 0), Number(yesterday[key] ?? 0)) : undefined)
  const items = [
    { key: 'total', title: '今日运行', value: today?.total ?? 0, delta: delta('total'), onClick: () => onGo('/runs') },
    { key: 'success_rate', title: '今日成功率', value: formatPercent(today?.success_rate), hint: '成功 / (成功 + 失败)' },
    { key: 'failed', title: '今日失败', value: today?.failed ?? 0, color: today?.failed ? '#dc2626' : undefined, delta: delta('failed'), onClick: () => onGo('/runs?status=failed') },
    { key: 'tokens', title: '今日 Token', value: formatNumber(today?.total_tokens ?? 0), delta: delta('total_tokens') },
    { key: 'cost', title: '今日成本', value: formatCost(today?.cost ?? 0), delta: delta('cost'), hint: '各运行收尾时的快照合计' },
    { key: 'latency', title: '平均耗时', value: formatDuration(today?.avg_latency_ms), hint: '只统计已结束的运行' },
  ]
  return <StatCards items={items} loading={loading} cols={6} />
}
