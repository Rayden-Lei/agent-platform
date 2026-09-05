import { useEffect } from 'react'
import { Button, Space, Typography } from 'antd'
import { CheckOutlined, CloseOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { getRun } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import ResourceLink from '../components/common/ResourceLink'
import TokenUsage from '../components/common/TokenUsage'
import RunOverview from '../components/runs/RunOverview'
import NodeLogTable from '../components/runs/NodeLogTable'
import { useReview } from '../components/runs/useReview'
import { formatDateTime, formatDuration } from '../utils/time'
import { formatCost } from '../utils/format'

// 运行详情页：概览 / 节点日志 / Token 与成本 / 关联；非终态时每 5 秒有界轮询（页面不可见暂停），待审核可直接通过 / 拒绝。
export default function RunDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const runId = Number(id)
  const { data: run, loading, error, reload } = useAsyncData(() => getRun(runId), [runId], { errorText: '加载运行详情失败' })
  const { reviewing, review } = useReview(() => reload(true))
  const live = run?.status === 'running' || run?.status === 'awaiting_review'

  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => { if (document.visibilityState === 'visible') reload(true) }, 5000)
    return () => clearInterval(timer)
  }, [live, reload])

  const meta = run ? [
    { label: '归属', value: run.run_type === 'chat' ? <ResourceLink type="agent" id={run.agent_id} name={run.agent_name} /> : <ResourceLink type="workflow" id={run.workflow_id} name={run.workflow_name} /> },
    { label: '触发', value: <span><StatusTag domain="runSource" value={run.source} /> {run.username}</span> },
    { label: '开始', value: formatDateTime(run.started_at) },
    { label: '耗时', value: run.finished_at ? formatDuration(run.latency_ms) : (live ? '进行中' : '-') },
  ] : []

  return (
    <DetailPage
      crumbs={[{ label: '运行记录', to: '/runs' }, { label: `#${runId}` }]}
      title={`运行 #${runId}`}
      tags={run && <Space size={4}><StatusTag domain="runType" value={run.run_type} /><StatusTag domain="run" value={run.status} /></Space>}
      meta={meta}
      loading={loading && !run}
      error={error}
      onRetry={() => reload()}
      backTo="/runs"
      extra={
        <Space>
          {run?.status === 'awaiting_review' && (
            <>
              <Button type="primary" icon={<CheckOutlined />} loading={reviewing === run.id} onClick={() => review(run, 'approved')}>通过</Button>
              <Button danger icon={<CloseOutlined />} loading={reviewing === run.id} onClick={() => review(run, 'rejected')}>拒绝</Button>
            </>
          )}
          {run?.conversation_id && <Button onClick={() => navigate(`/chat?conversation=${run.conversation_id}`)}>查看会话</Button>}
          <Button icon={<ReloadOutlined />} onClick={() => reload()}>{live ? '自动刷新中' : '刷新'}</Button>
        </Space>
      }
      tabs={run ? [
        { key: 'overview', label: '概览', children: <RunOverview run={run} /> },
        { key: 'nodes', label: `节点日志${run.nodes.length ? `（${run.nodes.length}）` : ''}`, children: <NodeLogTable nodes={run.nodes} /> },
        {
          key: 'tokens', label: 'Token 与成本', children: (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <TokenUsage usage={run.token_usage} cost={run.cost} />
              <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
                成本 {formatCost(run.cost)} 是运行收尾时按所用模型{run.model_name ? `「${run.model_name}」` : ''}当时的单价折算的快照，之后改单价不会追溯；工作流运行没有绑定模型，不计成本。
              </Typography.Paragraph>
            </div>
          ),
        },
      ] : []}
    />
  )
}
