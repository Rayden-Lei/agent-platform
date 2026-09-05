import { useState } from 'react'
import { Button, Popconfirm, Space, Tag, message } from 'antd'
import { DeleteOutlined, EditOutlined, MessageOutlined, RocketOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { deleteAgent, getAgent, publishAgent } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import DetailPage from '../components/layout/DetailPage'
import StatusTag from '../components/common/StatusTag'
import ResourceLink from '../components/common/ResourceLink'
import AgentForm from '../components/agents/AgentForm'
import AgentOverview from '../components/agents/AgentOverview'
import AgentStatsTab from '../components/agents/AgentStatsTab'
import AgentVersionsTab from '../components/agents/AgentVersionsTab'
import AgentConversationsTab from '../components/agents/AgentConversationsTab'
import RunsTable from '../components/runs/RunsTable'
import { errorText } from '../utils/errors'
import { formatDateTime } from '../utils/time'

// 智能体详情页：概览（关联可跳转）/ 运行统计 / 运行记录 / 会话 / 版本历史；头部可对话、编辑、发布、删除。
export default function AgentDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const agentId = Number(id)
  const { data: agent, loading, error, reload } = useAsyncData(() => getAgent(agentId), [agentId], { errorText: '加载智能体失败' })
  const [editing, setEditing] = useState(false)

  const publish = async () => {
    try { await publishAgent(agentId); message.success('已发布'); reload(true) } catch (e) { message.error(errorText(e, '发布失败')) }
  }
  const remove = async () => {
    try { await deleteAgent(agentId); message.success('已删除'); navigate('/agents') } catch (e) { message.error(errorText(e, '删除失败')) }
  }

  return (
    <>
      <DetailPage
        crumbs={[{ label: '智能体', to: '/agents' }, { label: agent?.name ?? `#${agentId}` }]}
        title={agent?.name ?? ''}
        tags={agent && <Space size={4}><StatusTag domain="agent" value={agent.status} /><Tag>v{agent.version}</Tag>{agent.prompt_template_outdated && <Tag color="orange">模板有新版本</Tag>}</Space>}
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
          <Space>
            <Button type="primary" icon={<MessageOutlined />} disabled={agent.status !== 'published'} onClick={() => navigate(`/chat?agent=${agent.id}`)}>对话</Button>
            {agent.status !== 'published' && <Button icon={<RocketOutlined />} onClick={publish}>发布</Button>}
            <Button icon={<EditOutlined />} onClick={() => setEditing(true)}>编辑</Button>
            <Popconfirm title="确定删除？会话、消息与运行记录会一并删除" onConfirm={remove}><Button danger icon={<DeleteOutlined />}>删除</Button></Popconfirm>
          </Space>
        )}
        tabs={agent ? [
          { key: 'overview', label: '概览', children: <AgentOverview agent={agent} /> },
          { key: 'stats', label: '运行统计', children: <AgentStatsTab agentId={agent.id} /> },
          { key: 'runs', label: '运行记录', children: <RunsTable filters={{ agent_id: agent.id }} /> },
          { key: 'conversations', label: '我的会话', children: <AgentConversationsTab agentId={agent.id} /> },
          { key: 'versions', label: `版本历史（v${agent.version}）`, children: <AgentVersionsTab agent={agent} onChanged={() => reload(true)} /> },
        ] : []}
      />
      <AgentForm open={editing} editing={agent} onClose={() => setEditing(false)} onSaved={() => reload(true)} />
    </>
  )
}
