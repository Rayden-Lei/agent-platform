import { Alert, Descriptions, Space, Tag, Typography } from 'antd'
import type { AgentDetail } from '../../api'
import JsonView from '../common/JsonView'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import { formatDateTime } from '../../utils/time'

// 智能体详情概览：关联对象（可跳转）、悬空引用提示、模型参数、系统提示词全文。
interface Props { agent: AgentDetail }

export default function AgentOverview({ agent }: Props) {
  const missing = [...agent.missing_tool_ids.map((i) => `工具 #${i}`), ...agent.missing_kb_ids.map((i) => `知识库 #${i}`)]
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {missing.length > 0 && <Alert type="warning" showIcon message="存在已删除的引用" description={`${missing.join('、')} 已不存在，但仍绑定在该智能体上；重新保存即可清理。`} />}
      {agent.model && !agent.model.is_enabled && <Alert type="error" showIcon message="绑定的模型已停用，对话会返回“模型不可用”" />}
      <Descriptions size="small" bordered column={{ xs: 1, md: 2 }} items={[
        { key: 'model', label: '模型', children: agent.model ? <Space><ResourceLink type="model" id={agent.model.id} name={agent.model.name} /><Typography.Text type="secondary">{agent.model.provider} / {agent.model.model_name}</Typography.Text><StatusTag domain="enabled" value={agent.model.is_enabled} /></Space> : '-' },
        { key: 'template', label: '提示词模板', children: agent.prompt_template ? <Space><ResourceLink type="template" id={agent.prompt_template.id} name={agent.prompt_template.name} /><Tag>绑定 v{agent.prompt_template_version} / 当前 v{agent.prompt_template.version}</Tag>{agent.prompt_template_outdated && <Tag color="orange">有新版本</Tag>}</Space> : <Typography.Text type="secondary">手填提示词</Typography.Text> },
        { key: 'tools', label: '工具', children: agent.tools.length ? <Space wrap>{agent.tools.map((t) => <span key={t.id}><ResourceLink type="tool" id={t.id} name={t.name} />{!t.is_enabled && <Tag color="default" style={{ marginLeft: 4 }}>已停用</Tag>}</span>)}</Space> : <Typography.Text type="secondary">只有内置工具</Typography.Text> },
        { key: 'kbs', label: '知识库', children: agent.knowledge_bases.length ? <Space wrap>{agent.knowledge_bases.map((k) => <span key={k.id}><ResourceLink type="kb" id={k.id} name={k.name} /><StatusTag domain="visibility" value={k.is_public} style={{ marginLeft: 4 }} /></span>)}</Space> : <Typography.Text type="secondary">未绑定</Typography.Text> },
        { key: 'workflow', label: '关联工作流', children: agent.workflow ? <ResourceLink type="workflow" id={agent.workflow.id} name={agent.workflow.name} /> : '-' },
        { key: 'creator', label: '创建人 / 时间', children: `${agent.created_by_username || '-'} / ${formatDateTime(agent.created_at)}` },
        { key: 'updated', label: '更新时间', children: formatDateTime(agent.updated_at) },
        { key: 'params', label: '模型参数', children: Object.keys(agent.params || {}).length ? <JsonView value={agent.params} maxHeight={120} /> : <Typography.Text type="secondary">模型默认值</Typography.Text> },
      ]} />
      {agent.prompt_template && Object.keys(agent.prompt_variables || {}).length > 0 && (
        <div>
          <Typography.Text strong>模板变量</Typography.Text>
          <JsonView value={agent.prompt_variables} maxHeight={160} />
        </div>
      )}
      <div>
        <Typography.Text strong>系统提示词{agent.prompt_template ? '（由模板渲染，重新保存即按最新版本更新）' : ''}</Typography.Text>
        <JsonView value={agent.system_prompt} maxHeight={320} />
      </div>
    </div>
  )
}
