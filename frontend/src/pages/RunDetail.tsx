import { useEffect } from 'react'
import { Check, RotateCw, X } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { getRun } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import ResourceLink from '../components/common/ResourceLink'
import TokenUsage from '../components/common/TokenUsage'
import RunOverview from '../components/runs/RunOverview'
import RunOwner from '../components/runs/RunOwner'
import NodeLogTable from '../components/runs/NodeLogTable'
import RunLlmCalls from '../components/runs/RunLlmCalls'
import Button from '../components/ui/Button'
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
    // 归属按实际填了哪个归属列判断：模型对话的 run_type 也是 chat，但没有智能体（docs/17 §3.1）
    { label: '归属', value: <RunOwner run={run} /> },
    { label: '触发', value: <span className="inline-flex items-center gap-1.5"><StatusTag domain="runSource" value={run.source} /> {run.username}</span> },
    { label: '开始', value: formatDateTime(run.started_at) },
    { label: '耗时', value: run.finished_at ? formatDuration(run.latency_ms) : (live ? '进行中' : '-') },
  ] : []

  return (
    <DetailPage
      crumbs={[{ label: '运行记录', to: '/runs' }, { label: `#${runId}` }]}
      title={`运行 #${runId}`}
      tags={run && <span className="inline-flex items-center gap-1"><StatusTag domain="runType" value={run.run_type} /><StatusTag domain="run" value={run.status} /></span>}
      meta={meta}
      loading={loading && !run}
      error={error}
      onRetry={() => reload()}
      backTo="/runs"
      extra={
        <span className="inline-flex items-center gap-2">
          {run?.status === 'awaiting_review' && (
            <>
              <Button variant="primary" size="md" icon={<Check />} disabled={reviewing === run.id} onClick={() => review(run, 'approved')}>
                {reviewing === run.id ? '提交中…' : '通过'}
              </Button>
              <Button variant="danger" size="md" icon={<X />} disabled={reviewing === run.id} onClick={() => review(run, 'rejected')}>拒绝</Button>
            </>
          )}
          {run?.conversation_id && (
            <Button size="md" variant="secondary" onClick={() => navigate(`/chat?conversation=${run.conversation_id}`)}>查看会话</Button>
          )}
          <Button size="md" variant="secondary" icon={<RotateCw />} onClick={() => reload()}>{live ? '自动刷新中' : '刷新'}</Button>
        </span>
      }
      tabs={run ? [
        { key: 'overview', label: '概览', children: <RunOverview run={run} /> },
        { key: 'nodes', label: `节点日志${run.nodes.length ? `（${run.nodes.length}）` : ''}`, children: <NodeLogTable nodes={run.nodes} /> },
        // 上游视角的报文：调用链说"这一步做了什么"，这里说"上游实际收到与返回了什么"
        { key: 'llm-calls', label: '模型调用', children: <RunLlmCalls runId={run.id} /> },
        {
          key: 'tokens', label: 'Token 与成本', children: (
            <div className="flex flex-col gap-3">
              <TokenUsage usage={run.token_usage} cost={run.cost} />
              <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
                成本 {formatCost(run.cost)} 是运行收尾时按所用模型{run.model_name ? `「${run.model_name}」` : ''}当时的单价折算的快照，之后改单价不会追溯；工作流运行没有绑定模型，不计成本。
              </p>
            </div>
          ),
        },
      ] : []}
    />
  )
}
