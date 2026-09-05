import { useState } from 'react'
import { Col, Radio, Row } from 'antd'
import { getAgentUsage, getDailyRunStats, getWorkflowUsage, type AgentUsageRow, type WorkflowUsageRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import ChartCard from '../charts/ChartCard'
import TrendLine from '../charts/TrendLine'
import { STATUS_SERIES_LABEL } from '../charts/theme'
import StatCards from '../layout/StatCards'
import { compactNumber, formatCost, formatNumber, formatPercent } from '../../utils/format'
import { formatDuration } from '../../utils/time'

// 单个对象的运行统计页签（智能体 / 工作流共用）：区间内指标卡 + 按状态趋势 + Token 趋势。
interface Props {
  agentId?: number
  workflowId?: number
}

export default function AgentStatsTab({ agentId, workflowId }: Props) {
  const [days, setDays] = useState(7)
  const filter = agentId ? { agent_id: agentId } : { workflow_id: workflowId }
  type UsageResult = { days: number; items: (AgentUsageRow | WorkflowUsageRow)[] }
  const usage = useAsyncData<UsageResult>(() => (agentId ? getAgentUsage({ days, agent_id: agentId }) : getWorkflowUsage({ days, workflow_id: workflowId })), [days, agentId, workflowId])
  const daily = useAsyncData(() => getDailyRunStats({ days, ...filter }), [days, agentId, workflowId])
  const row = usage.data?.items[0]
  const items = [
    { key: 'total', title: '运行', value: row?.total ?? 0 },
    { key: 'rate', title: '成功率', value: formatPercent(row?.success_rate) },
    { key: 'failed', title: '失败', value: row?.failed ?? 0, color: row?.failed ? '#dc2626' : undefined },
    { key: 'latency', title: '平均耗时', value: formatDuration(row?.avg_latency_ms) },
    { key: 'tokens', title: 'Token', value: formatNumber(row?.total_tokens ?? 0) },
    { key: 'cost', title: '成本', value: formatCost(row?.cost ?? 0) },
    ...(agentId && row && 'conversations' in row ? [
      { key: 'conv', title: '会话数', value: (row as { conversations: number }).conversations },
      { key: 'msg', title: '消息数', value: (row as { messages: number }).messages },
    ] : []),
  ]
  const series = ['success', 'failed', 'cancelled', 'awaiting_review', 'running'] as const
  const points = (daily.data?.items ?? []).flatMap((d) => series.map((s) => ({ date: d.date.slice(5), value: Number(d[s] ?? 0), series: STATUS_SERIES_LABEL[s] })))
  const tokens = (daily.data?.items ?? []).map((d) => ({ date: d.date.slice(5), value: d.total_tokens }))
  const hasData = (daily.data?.items ?? []).some((d) => d.total > 0)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Radio.Group size="small" value={days} onChange={(e) => setDays(e.target.value)} optionType="button" options={[{ label: '近 7 天', value: 7 }, { label: '近 30 天', value: 30 }, { label: '近 90 天', value: 90 }]} />
      </div>
      <StatCards items={items} loading={usage.loading && !usage.data} cols={4} />
      <Row gutter={[12, 12]}>
        <Col xs={24} lg={14}>
          <ChartCard title="运行趋势（按状态）" loading={daily.loading && !daily.data} error={daily.error} onRetry={() => daily.reload()} empty={!hasData} emptyText="区间内没有运行">
            <TrendLine data={points} height={236} statusSeries yFormatter={compactNumber} />
          </ChartCard>
        </Col>
        <Col xs={24} lg={10}>
          <ChartCard title="Token 消耗趋势" loading={daily.loading && !daily.data} error={daily.error} onRetry={() => daily.reload()} empty={!tokens.some((t) => t.value > 0)} emptyText="区间内没有 Token 消耗">
            <TrendLine data={tokens} height={236} area yFormatter={compactNumber} />
          </ChartCard>
        </Col>
      </Row>
    </div>
  )
}
