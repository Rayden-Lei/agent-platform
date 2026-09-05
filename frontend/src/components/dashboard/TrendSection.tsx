import { Col, Radio, Row } from 'antd'
import type { DailyRunStat } from '../../api'
import ChartCard from '../charts/ChartCard'
import Donut from '../charts/Donut'
import TrendLine from '../charts/TrendLine'
import { STATUS_SERIES_LABEL } from '../charts/theme'
import { compactNumber } from '../../utils/format'

// 趋势区：按天运行数（按状态分序列）+ 区间内状态分布环图；区间切换 7 / 30 天。
const SERIES: (keyof DailyRunStat)[] = ['success', 'failed', 'cancelled', 'awaiting_review', 'running']

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
  const picker = <Radio.Group size="small" value={days} onChange={(e) => onDaysChange(e.target.value)} options={[{ label: '近 7 天', value: 7 }, { label: '近 30 天', value: 30 }]} optionType="button" />
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} lg={16}>
        <ChartCard title="运行趋势（按状态）" extra={picker} loading={loading} error={error} onRetry={onRetry} empty={!hasData} emptyText="区间内没有运行记录">
          <TrendLine data={points} height={236} statusSeries yFormatter={compactNumber} />
        </ChartCard>
      </Col>
      <Col xs={24} lg={8}>
        <ChartCard title="状态分布" loading={loading} error={error} onRetry={onRetry} empty={!hasData}>
          <Donut data={totals} height={236} statusColors />
        </ChartCard>
      </Col>
    </Row>
  )
}
