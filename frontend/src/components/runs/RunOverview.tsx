import type { ReactNode } from 'react'
import { AlertTriangle, XCircle } from 'lucide-react'
import type { RunDetail } from '../../api'
import JsonView from '../common/JsonView'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TokenUsage from '../common/TokenUsage'
import { formatDateTime, formatDuration } from '../../utils/time'

// 运行详情概览：关键信息 + 输入 / 输出 + 错误 / 待审核中断信息。
interface Props { run: RunDetail }

// 提示条：警告用中性底 + 警告图标，错误用红色描边 —— 不写死色值，全走语义 token
function Notice({ tone, title, children }: { tone: 'warning' | 'error'; title: ReactNode; children?: ReactNode }) {
  const Icon = tone === 'error' ? XCircle : AlertTriangle
  return (
    <div className={`flex items-start gap-2 rounded-lg border bg-secondary px-3 py-2 ${tone === 'error' ? 'border-destructive/40' : 'border-border'}`}>
      <Icon className={`mt-0.5 size-4 shrink-0 ${tone === 'error' ? 'text-destructive' : 'text-muted-foreground'}`} aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className={`m-0 text-[13.5px] font-medium ${tone === 'error' ? 'text-destructive' : 'text-foreground'}`}>{title}</p>
        {children && <div className="mt-1">{children}</div>}
      </div>
    </div>
  )
}

// 概览的一格：左侧固定标签宽度，右侧值可换行
function Cell({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[112px_1fr] items-start gap-2.5 bg-card px-3 py-2">
      <span className="text-[12.5px] leading-5 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-[13.5px] leading-5 text-foreground">{children}</span>
    </div>
  )
}

export default function RunOverview({ run }: Props) {
  const interrupt = (run.output as { interrupt?: unknown } | null)?.interrupt
  return (
    <div className="flex flex-col gap-4">
      {run.status === 'awaiting_review' && (
        <Notice tone="warning" title="等待人工审核">
          <JsonView title="中断信息" value={interrupt} maxHeight={160} />
        </Notice>
      )}
      {run.error && (
        <Notice tone="error" title="运行失败">
          <pre className="m-0 whitespace-pre-wrap text-[12.5px] leading-relaxed text-foreground">{run.error}</pre>
        </Notice>
      )}

      <div className="grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-border bg-border md:grid-cols-2">
        <Cell label="类型"><StatusTag domain="runType" value={run.run_type} /></Cell>
        <Cell label="状态"><StatusTag domain="run" value={run.status} /></Cell>
        <Cell label="归属">
          {run.run_type === 'chat'
            ? <ResourceLink type="agent" id={run.agent_id} name={run.agent_name} showIcon />
            : <ResourceLink type="workflow" id={run.workflow_id} name={run.workflow_name} showIcon />}
        </Cell>
        <Cell label="触发">
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <StatusTag domain="runSource" value={run.source} />
            {run.username && <span>{run.username}</span>}
            {run.schedule_id && <ResourceLink type="schedule" id={run.schedule_id} name={`定时任务 #${run.schedule_id}`} />}
          </span>
        </Cell>
        <Cell label="模型">{run.model_id ? <ResourceLink type="model" id={run.model_id} name={run.model_name} /> : '-'}</Cell>
        <Cell label="会话">{run.conversation_id ? <ResourceLink type="conversation" id={run.conversation_id} name={`会话 #${run.conversation_id}`} /> : '-'}</Cell>
        <Cell label="开始">{formatDateTime(run.started_at)}</Cell>
        <Cell label="结束">{formatDateTime(run.finished_at)}</Cell>
        <Cell label="耗时">{run.finished_at ? formatDuration(run.latency_ms) : (run.status === 'running' || run.status === 'awaiting_review' ? '进行中' : '-')}</Cell>
        <Cell label="Token / 成本"><TokenUsage usage={run.token_usage} cost={run.cost} /></Cell>
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-[13.5px] font-medium text-foreground">输入</span>
        <JsonView value={run.input} maxHeight={220} />
      </div>
      <div className="flex flex-col gap-2">
        <span className="text-[13.5px] font-medium text-foreground">输出</span>
        <JsonView value={run.output} maxHeight={320} />
      </div>
    </div>
  )
}
