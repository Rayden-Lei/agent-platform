import { useState } from 'react'
import { toast } from 'sonner'
import { Copy, Pencil, Play, Rocket, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { deleteWorkflow, duplicateWorkflow, getWorkflow, getWorkflowParameters, publishWorkflow } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { usePublicBaseUrl } from '../hooks/usePublicBaseUrl'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import TimeCell from '../components/common/TimeCell'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import InlineConfirm from '../components/ui/InlineConfirm'
import AgentStatsTab from '../components/agents/AgentStatsTab'
import RunsTable from '../components/runs/RunsTable'
import WorkflowOverview from '../components/workflows/WorkflowOverview'
import WorkflowVersionsTab from '../components/workflows/WorkflowVersionsTab'
import WorkflowPublishModal from '../components/workflows/WorkflowPublishModal'
import WorkflowApiAccessPanel from '../components/workflows/WorkflowApiAccessPanel'
import RunWorkflowModal from '../components/workflows/RunWorkflowModal'
import { errorText } from '../utils/errors'

// 工作流详情页：概览（流程图 / 定时任务 / 引用）、版本历史、运行统计、运行记录、API 访问；
// 头部运行 / 发布 / 编辑 / 复制 / 删除。
export default function WorkflowDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const wfId = Number(id)
  const { data: wf, loading, error, reload } = useAsyncData(() => getWorkflow(wfId), [wfId], { errorText: '加载工作流失败' })
  // API 访问页签的入参声明读的是**线上版本**（WF-04 / FR-075）：草稿改了不影响对外契约，所以单独取一次，
  // 并且只在有线上版本时取（未发布时面板只提示"先发布"，不显示示例）
  const published = !!wf?.published_version
  const { baseUrl, configured: baseUrlConfigured } = usePublicBaseUrl()
  const { data: parameters, error: parametersError, reload: reloadParameters } = useAsyncData(
    () => getWorkflowParameters(wfId), [wfId, published], { errorText: '加载入参声明失败', auto: published },
  )
  const [running, setRunning] = useState(false)
  const [showPublish, setShowPublish] = useState(false)

  const remove = async () => {
    try { await deleteWorkflow(wfId); toast.success('已删除'); navigate('/workflows') } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  const duplicate = async () => {
    try {
      const copy = await duplicateWorkflow(wfId)
      toast.success(`已复制为「${copy.name}」（草稿，未发布）`)
      navigate(`/workflows/${copy.id}`)
    } catch (e) { toast.error(errorText(e, '复制失败')) }
  }
  const doPublish = async (note?: string) => {
    try {
      const r = await publishWorkflow(wfId, note)
      toast.success(r.publish_result === 'unchanged' ? '草稿与线上一致，无需发布' : `已发布，线上为 v${r.published_version}`)
      setShowPublish(false)
      reload()
    } catch (e) { toast.error(errorText(e, '发布失败')); throw e }
  }

  return (
    <>
      <DetailPage
        crumbs={[{ label: '工作流', to: '/workflows' }, { label: wf?.name ?? `#${wfId}` }]}
        title={wf?.name ?? ''}
        tags={wf && (
          <span className="inline-flex items-center gap-1.5">
            <StatusTag domain="workflow" value={wf.status} />
            {/* 显示的是**线上版本号**：草稿修订号只在编辑器里才有意义，详情页关心"对外是哪一版" */}
            <Badge tone="neutral">{wf.published_version ? `线上 v${wf.published_version}` : '未发布'}</Badge>
            {wf.has_unpublished_changes && <Badge tone="warning">有未发布改动</Badge>}
          </span>
        )}
        meta={wf ? [
          { label: '节点', value: wf.node_count },
          { label: '定时任务', value: wf.schedules_count },
          { label: '近 7 天运行', value: wf.runs_7d ? <Link className="text-primary hover:underline" to={`/runs?workflow_id=${wf.id}`}>{wf.runs_7d}</Link> : 0 },
          { label: '最近运行', value: <TimeCell value={wf.last_run_at} mode="relative" /> },
          { label: '创建人', value: wf.created_by_username || '-' },
          // 发布日期为空表示还没发布过（与"发布"按钮的可用状态同一口径）
          { label: '发布时间', value: wf.published_at ? <TimeCell value={wf.published_at} /> : '-' },
        ] : []}
        loading={loading && !wf}
        error={error}
        onRetry={() => reload()}
        backTo="/workflows"
        extra={wf && (
          <>
            {/* 未发布时"运行"无从跑起（后端 403），按钮禁用并说明原因；发布后才能运行 */}
            <Button variant="primary" size="md" icon={<Play />} disabled={!wf.node_count || !wf.published_version}
              title={wf.published_version ? undefined : '工作流还没发布，不能运行'} onClick={() => setRunning(true)}>运行</Button>
            {(wf.published_version === null || wf.has_unpublished_changes) && (
              <Button variant="secondary" size="md" icon={<Rocket />} onClick={() => setShowPublish(true)}>发布</Button>
            )}
            <Button variant="secondary" size="md" icon={<Pencil />} onClick={() => navigate(`/workflows/${wf.id}/edit`)}>编辑</Button>
            <Button variant="secondary" size="md" icon={<Copy />} onClick={duplicate}>复制</Button>
            <InlineConfirm message="确定删除？关联的定时任务会一并删除" danger onConfirm={remove}>
              <Button variant="danger" size="md" icon={<Trash2 />}>删除</Button>
            </InlineConfirm>
          </>
        )}
        tabs={wf ? [
          { key: 'overview', label: '概览', children: <WorkflowOverview workflow={wf} /> },
          // 版本历史：发布快照不可变，可回滚上线（线上止血）或恢复到草稿（在旧版本上继续改）
          { key: 'versions', label: '版本历史', children: <WorkflowVersionsTab workflow={wf} onChanged={() => reload()} /> },
          { key: 'stats', label: '运行统计', children: <AgentStatsTab workflowId={wf.id} /> },
          { key: 'runs', label: '运行记录', children: <RunsTable filters={{ workflow_id: wf.id }} hideOwner={false} /> },
          // API 访问（WF-06）：Base URL / 工作流 ID / 鉴权 + 同步、异步轮询、取消、续跑四段示例与错误码
          {
            key: 'api',
            label: 'API 访问',
            children: (
              <WorkflowApiAccessPanel
                workflow={wf}
                baseUrl={baseUrl}
                baseUrlConfigured={baseUrlConfigured}
                parameters={published ? parameters : null}
                parametersError={parametersError}
                onRetryParameters={() => reloadParameters()}
              />
            ),
          },
        ] : []}
      />
      {wf && <RunWorkflowModal workflow={running ? wf : null} onClose={() => setRunning(false)} onDone={() => reload(true)} />}
      <WorkflowPublishModal
        target={showPublish && wf ? {
          name: wf.name, draftVersion: wf.version, publishedVersion: wf.published_version, nodeCount: wf.node_count,
        } : null}
        onClose={() => setShowPublish(false)}
        onPublish={doPublish}
      />
    </>
  )
}
