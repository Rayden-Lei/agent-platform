import { useState } from 'react'
import { Button, Col, Row } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import type { RunsSummary } from '../../api'
import ChartCard from '../charts/ChartCard'
import StackedBar from '../charts/StackedBar'
import StatCards from '../layout/StatCards'
import { formatCost, formatNumber, formatPercent } from '../../utils/format'
import { formatDuration } from '../../utils/time'

// 运行记录统计卡：随筛选联动；点状态卡即筛选；可展开耗时分布图。
interface Props {
  summary: RunsSummary | null
  loading: boolean
  activeStatus?: string
  onPickStatus: (status?: string) => void
}

export default function RunStatCards({ summary, loading, activeStatus, onPickStatus }: Props) {
  const [showLatency, setShowLatency] = useState(false)
  const pick = (status: string) => () => onPickStatus(activeStatus === status ? undefined : status)
  const s = summary
  const items = [
    { key: 'total', title: '总运行', value: s?.total ?? 0, onClick: () => onPickStatus(undefined), active: !activeStatus },
    { key: 'running', title: '运行中', value: s?.running ?? 0, color: '#2563eb', onClick: pick('running'), active: activeStatus === 'running' },
    { key: 'awaiting_review', title: '待审核', value: s?.awaiting_review ?? 0, color: '#d97706', onClick: pick('awaiting_review'), active: activeStatus === 'awaiting_review', hint: '人工审核节点暂停的工作流，点击查看并处理' },
    { key: 'success', title: '成功', value: s?.success ?? 0, color: '#16a34a', onClick: pick('success'), active: activeStatus === 'success' },
    { key: 'failed', title: '失败', value: s?.failed ?? 0, color: '#dc2626', onClick: pick('failed'), active: activeStatus === 'failed' },
    { key: 'success_rate', title: '成功率', value: formatPercent(s?.success_rate), hint: '成功 / (成功 + 失败)，不含取消与进行中' },
    { key: 'latency', title: '平均 / P95 耗时', value: `${formatDuration(s?.avg_latency_ms)} / ${formatDuration(s?.p95_latency_ms)}`, hint: '只统计已结束的运行' },
    { key: 'tokens', title: 'Token / 成本', value: `${formatNumber(s?.total_tokens ?? 0)} / ${formatCost(s?.total_cost ?? 0)}`, hint: `输入 ${formatNumber(s?.prompt_tokens ?? 0)}，输出 ${formatNumber(s?.completion_tokens ?? 0)}；成本为各运行收尾时的快照合计` },
  ]
  const buckets = (s?.latency_buckets ?? []).map((b) => ({ x: b.label, value: b.count }))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <StatCards items={items} loading={loading} cols={8} />
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <Button size="small" type="link" icon={<BarChartOutlined />} onClick={() => setShowLatency(!showLatency)}>{showLatency ? '收起耗时分布' : '耗时分布'}</Button>
      </div>
      {showLatency && (
        <Row>
          <Col span={24}>
            <ChartCard title="耗时分布（已结束的运行）" height={200} loading={loading} empty={!buckets.some((b) => b.value > 0)} emptyText="当前筛选下没有已结束的运行">
              <StackedBar data={buckets} height={176} />
            </ChartCard>
          </Col>
        </Row>
      )}
    </div>
  )
}
