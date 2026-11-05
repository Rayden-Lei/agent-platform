import { useState } from 'react'
import { toast } from 'sonner'
import { MessageSquare, Pencil, Rocket, Share2, Trash2 } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { deleteAgent, getAgent, listApiKeys, offlineAgent, publishAgent } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { usePublicBaseUrl } from '../hooks/usePublicBaseUrl'
import { useApiKeyScopeOptions } from '../hooks/useApiKeyScopeOptions'
import { useAgentShare } from '../hooks/useAgentShare'
import ShareLinkCard from '../components/publish/ShareLinkCard'
import ApiAccessPanel from '../components/publish/ApiAccessPanel'
import AgentKeysCard from '../components/publish/AgentKeysCard'
import ApiKeyForm from '../components/admin/ApiKeyForm'
import CreatedKeyModal from '../components/admin/CreatedKeyModal'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import ResourceLink from '../components/common/ResourceLink'
import PublishModal from '../components/agents/PublishModal'
import AgentOverview from '../components/agents/AgentOverview'
import AgentStatsTab from '../components/agents/AgentStatsTab'
import AgentVersionsTab from '../components/agents/AgentVersionsTab'
import AgentConversationsTab from '../components/agents/AgentConversationsTab'
import RunsTable from '../components/runs/RunsTable'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import InlineConfirm from '../components/ui/InlineConfirm'
import { errorText } from '../utils/errors'
import { formatDateTime } from '../utils/time'

// 智能体详情页：概览（关联可跳转）/ 发布渠道（分享链接、API 调用与密钥）/ 运行统计 / 运行记录 / 会话 / 版本历史；
// 头部可对话、分享（跳发布渠道）、编辑（进装配页）、发布（弹窗）、下线、删除。发布渠道的取数（分享配置、对外地址、作用域含本智能体的 Key）在本页面与 hooks。
export default function AgentDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const agentId = Number(id)
  const { data: agent, loading, error, reload } = useAsyncData(() => getAgent(agentId), [agentId], { errorText: '加载智能体失败' })
  const [publishOpen, setPublishOpen] = useState(false)
  const { baseUrl, configured: baseUrlConfigured } = usePublicBaseUrl()
  const keys = useAsyncData(() => listApiKeys({ agent_id: agentId, page: 1, page_size: 50 }), [agentId], { errorText: '加载密钥失败' })
  const [keyFormOpen, setKeyFormOpen] = useState(false)
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const scopeOptions = useApiKeyScopeOptions(keyFormOpen)
  const share = useAgentShare(agentId)

  const publish = async (note?: string) => {
    try {
      const r = await publishAgent(agentId, note)
      toast.success(r.publish_result === 'unchanged' ? '草稿与线上一致，无需发布' : `已发布，线上为 v${r.published_version}`)
      setPublishOpen(false)
      reload(true)
      share.reload(true) // 分享的"已发布"与预检随线上版本变
    } catch (e) { toast.error(errorText(e, '发布失败')); throw e }
  }
  const takeOffline = async () => {
    try { await offlineAgent(agentId); toast.success('已下线：对话、分享链接、API Key 与工作流都不能再调用它'); reload(true); share.reload(true) } catch (e) { toast.error(errorText(e, '下线失败')) }
  }
  const remove = async () => {
    try { await deleteAgent(agentId); toast.success('已删除'); navigate('/agents') } catch (e) { toast.error(errorText(e, '删除失败')) }
  }

  return (
    <>
      <DetailPage
        crumbs={[{ label: '智能体', to: '/agents' }, { label: agent?.name ?? `#${agentId}` }]}
        title={agent?.name ?? ''}
        tags={agent && (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <StatusTag domain="agent" value={agent.status} />
            {agent.published_version && <Badge tone="neutral">线上 v{agent.published_version}</Badge>}
            {agent.has_unpublished_changes && <Badge tone="warning">未发布修改</Badge>}
            {agent.prompt_template_outdated && <Badge tone="warning">模板有新版本</Badge>}
          </span>
        )}
        meta={agent ? [
          { label: '模型', value: <ResourceLink type="model" id={agent.model_id} name={agent.model_name} /> },
          { label: '近 7 天运行', value: agent.runs_7d },
          { label: '创建人', value: agent.created_by_username || '-' },
          { label: '更新时间', value: formatDateTime(agent.updated_at) },
        ] : []}
        loading={loading && !agent}
        error={error}
        onRetry={() => reload()}
        backTo="/agents"
        extra={agent && (
          <>
            <Button variant="primary" size="md" disabled={agent.status !== 'published'} onClick={() => navigate(`/chat?agent=${agent.id}`)}>
              <MessageSquare className="size-3.5" />对话
            </Button>
            <Button variant="secondary" size="md" onClick={() => navigate('?tab=channels')}>
              <Share2 className="size-3.5" />分享
            </Button>
            {(agent.status !== 'published' || agent.has_unpublished_changes) && (
              <Button variant="secondary" size="md" onClick={() => setPublishOpen(true)}>
                <Rocket className="size-3.5" />{agent.status === 'offline' && !agent.has_unpublished_changes ? '重新上线' : '发布'}
              </Button>
            )}
            {agent.status === 'published' && (
              <InlineConfirm message="下线后对话、API Key 与工作流都不能再调用它，重新发布即恢复。确定下线？" confirmLabel="下线" danger onConfirm={takeOffline}>
                <Button variant="secondary" size="md">下线</Button>
              </InlineConfirm>
            )}
            <Button variant="secondary" size="md" onClick={() => navigate(`/agents/${agent.id}/edit`)}>
              <Pencil className="size-3.5" />编辑
            </Button>
            <InlineConfirm message="确定删除？会话、消息与运行记录会一并删除" danger onConfirm={remove}>
              <Button variant="danger" size="md"><Trash2 className="size-3.5" />删除</Button>
            </InlineConfirm>
          </>
        )}
        tabs={agent ? [
          { key: 'overview', label: '概览', children: <AgentOverview agent={agent} /> },
          {
            key: 'channels', label: '发布渠道', children: (
              <div className="flex flex-col gap-3">
                <ShareLinkCard share={share.share} error={share.error} saving={share.saving} onRetry={() => share.reload()} onSave={share.save} onReset={share.reset} />
                <ApiAccessPanel agent={agent} baseUrl={baseUrl} baseUrlConfigured={baseUrlConfigured} />
                <AgentKeysCard keys={keys.data?.items ?? null} total={keys.data?.total} error={keys.error} onRetry={() => keys.reload()} onCreate={() => setKeyFormOpen(true)} />
              </div>
            ),
          },
          { key: 'stats', label: '运行统计', children: <AgentStatsTab agentId={agent.id} /> },
          { key: 'runs', label: '运行记录', children: <RunsTable filters={{ agent_id: agent.id }} /> },
          { key: 'conversations', label: '我的会话', children: <AgentConversationsTab agentId={agent.id} /> },
          { key: 'versions', label: agent.published_version ? `版本历史（线上 v${agent.published_version}）` : '版本历史', children: <AgentVersionsTab agent={agent} onChanged={() => reload(true)} /> },
        ] : []}
      />
      <PublishModal agent={publishOpen ? agent : null} onClose={() => setPublishOpen(false)} onPublish={publish} />
      <ApiKeyForm open={keyFormOpen} editing={null} scopeOptions={scopeOptions} initialScope={{ agent_ids: [agentId] }}
        onClose={() => setKeyFormOpen(false)} onSaved={() => keys.reload(true)} onCreated={setCreatedKey} />
      <CreatedKeyModal value={createdKey} onClose={() => setCreatedKey(null)} />
    </>
  )
}
