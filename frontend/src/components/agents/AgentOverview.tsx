import type { ReactNode } from 'react'
import { AlertTriangle, XCircle } from 'lucide-react'
import type { AgentDetail } from '../../api'
import JsonView from '../common/JsonView'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import Badge from '../ui/Badge'
import { formatDateTime } from '../../utils/time'

// 智能体详情概览：关联对象（可跳转）、悬空引用提示、模型参数、系统提示词全文。
interface Props { agent: AgentDetail }

// 提示条：警告用中性底 + 警告图标，错误用红色描边 —— 不写死色值，全走语义 token
function Notice({ tone, title, children }: { tone: 'warning' | 'error'; title: ReactNode; children?: ReactNode }) {
  const Icon = tone === 'error' ? XCircle : AlertTriangle
  return (
    <div className={`flex items-start gap-2 rounded-lg border bg-secondary px-3 py-2 ${tone === 'error' ? 'border-destructive/40' : 'border-border'}`}>
      <Icon className={`mt-0.5 size-4 shrink-0 ${tone === 'error' ? 'text-destructive' : 'text-muted-foreground'}`} aria-hidden="true" />
      <div className="min-w-0">
        <p className={`m-0 text-[13.5px] font-medium ${tone === 'error' ? 'text-destructive' : 'text-foreground'}`}>{title}</p>
        {children && <p className="m-0 mt-0.5 text-[12.5px] leading-relaxed text-muted-foreground">{children}</p>}
      </div>
    </div>
  )
}

// 概览的一格：左侧固定标签宽度，右侧值可换行（窄屏单列、宽屏两列）
function Cell({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[104px_1fr] items-start gap-2.5 bg-card px-3 py-2">
      <span className="text-[12.5px] leading-5 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-[13.5px] leading-5 text-foreground">{children}</span>
    </div>
  )
}

export default function AgentOverview({ agent }: Props) {
  const missing = [...agent.missing_tool_ids.map((i) => `工具 #${i}`), ...agent.missing_kb_ids.map((i) => `知识库 #${i}`)]
  return (
    <div className="flex flex-col gap-4">
      {missing.length > 0 && (
        <Notice tone="warning" title="存在已删除的引用">
          {missing.join('、')} 已不存在，但仍绑定在该智能体上；重新保存即可清理。
        </Notice>
      )}
      {agent.model && !agent.model.is_enabled && (
        <Notice tone="error" title="绑定的模型已停用，对话会返回“模型不可用”" />
      )}

      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-2">
        <Cell label="模型">
          {agent.model ? (
            <span className="inline-flex flex-wrap items-center gap-2">
              <ResourceLink type="model" id={agent.model.id} name={agent.model.name} />
              <span className="text-muted-foreground">{agent.model.provider} / {agent.model.model_name}</span>
              <StatusTag domain="enabled" value={agent.model.is_enabled} />
            </span>
          ) : '-'}
        </Cell>
        <Cell label="提示词模板">
          {agent.prompt_template ? (
            <span className="inline-flex flex-wrap items-center gap-2">
              <ResourceLink type="template" id={agent.prompt_template.id} name={agent.prompt_template.name} />
              <Badge tone="neutral">绑定 v{agent.prompt_template_version} / 当前 v{agent.prompt_template.version}</Badge>
              {agent.prompt_template_outdated && <Badge tone="warning">有新版本</Badge>}
            </span>
          ) : <span className="text-muted-foreground">手填提示词</span>}
        </Cell>
        <Cell label="工具">
          {agent.tools.length ? (
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              {agent.tools.map((t) => (
                <span key={t.id} className="inline-flex items-center gap-1">
                  <ResourceLink type="tool" id={t.id} name={t.name} />
                  {!t.is_enabled && <Badge tone="neutral">已停用</Badge>}
                </span>
              ))}
            </span>
          ) : <span className="text-muted-foreground">只有内置工具</span>}
        </Cell>
        <Cell label="知识库">
          {agent.knowledge_bases.length ? (
            <span className="inline-flex flex-wrap items-center gap-x-2 gap-y-1">
              {agent.knowledge_bases.map((k) => (
                <span key={k.id} className="inline-flex items-center gap-1">
                  <ResourceLink type="kb" id={k.id} name={k.name} />
                  <StatusTag domain="visibility" value={k.is_public} />
                </span>
              ))}
            </span>
          ) : <span className="text-muted-foreground">未绑定</span>}
        </Cell>
        <Cell label="关联工作流">
          {agent.workflow ? <ResourceLink type="workflow" id={agent.workflow.id} name={agent.workflow.name} /> : '-'}
        </Cell>
        <Cell label="创建人 / 时间">{agent.created_by_username || '-'} / {formatDateTime(agent.created_at)}</Cell>
        <Cell label="更新时间">{formatDateTime(agent.updated_at)}</Cell>
        <Cell label="模型参数">
          {Object.keys(agent.params || {}).length
            ? <JsonView value={agent.params} maxHeight={120} />
            : <span className="text-muted-foreground">模型默认值</span>}
        </Cell>
      </div>

      {agent.prompt_template && Object.keys(agent.prompt_variables || {}).length > 0 && (
        <div className="flex flex-col gap-2">
          <span className="text-[13.5px] font-medium text-foreground">模板变量</span>
          <JsonView value={agent.prompt_variables} maxHeight={160} />
        </div>
      )}

      <div className="flex flex-col gap-2">
        <span className="text-[13.5px] font-medium text-foreground">
          系统提示词{agent.prompt_template ? '（由模板渲染，重新保存即按最新版本更新）' : ''}
        </span>
        <JsonView value={agent.system_prompt} maxHeight={320} />
      </div>
    </div>
  )
}
