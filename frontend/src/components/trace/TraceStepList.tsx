import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import type { TraceStep } from '../../api'
import JsonView from '../common/JsonView'
import Badge from '../ui/Badge'
import { formatDuration } from '../../utils/time'

// 调用链步骤列表（docs/15 3.4）：按发生顺序列出改写 / 检索 / 模型调用 / 工具执行，展开看入参与结果。
// 装配页调试的"详情"在用；第 2 批运行详情的"调用链"页签（OP-08）沿用同一组件与同一结构。
// 手风琴自己拼：可以同时展开多步，样式全走 token（shadcn 没有 collapse）。
export const STEP_TYPE_LABEL: Record<string, { text: string; color: string }> = {
  rewrite: { text: '改写', color: 'purple' },
  retrieve: { text: '检索', color: 'blue' },
  llm: { text: '模型', color: 'geekblue' },
  tool: { text: '工具', color: 'orange' },
}
const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  error: { text: '失败', color: 'error' },
  denied: { text: '无权检索', color: 'warning' },
}

function stepSummary(step: TraceStep): string {
  const m = step.meta || {}
  if (step.type === 'retrieve') return `候选 ${m.candidate_count ?? 0} · 返回 ${m.returned ?? 0}${m.acl_rejected ? ` · 鉴权剔除 ${m.acl_rejected}` : ''}`
  if (step.type === 'llm') {
    const usage = m.usage?.total_tokens ? ` · Token ${m.usage.total_tokens}` : ''
    const tools = step.output?.tool_calls?.length ? ` · 请求工具 ${step.output.tool_calls.join('、')}` : ''
    return `${m.first_token_ms != null ? `首字 ${formatDuration(m.first_token_ms)}` : '无文本输出'}${usage}${tools}`
  }
  return ''
}

export default function TraceStepList({ steps }: { steps: TraceStep[] }) {
  const [open, setOpen] = useState<string[]>([])
  if (!steps.length) return <span className="text-[13.5px] text-muted-foreground">这一轮没有记录到调用步骤</span>
  const toggle = (key: string) => setOpen((keys) => (keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key]))

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      {steps.map((step, i) => {
        const key = step.id || String(i)
        const expanded = open.includes(key)
        const type = STEP_TYPE_LABEL[step.type] ?? { text: step.type, color: 'default' }
        const status = STATUS_LABEL[step.status]
        return (
          <div key={key} className={i ? 'border-t border-border' : undefined}>
            <button
              type="button"
              onClick={() => toggle(key)}
              aria-expanded={expanded}
              className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent"
            >
              {expanded
                ? <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
                : <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
              <Badge tone={type.color}>{type.text}</Badge>
              <span className="text-[13.5px] font-medium">{step.name}</span>
              {status && <Badge tone={status.color}>{status.text}</Badge>}
              <span className="ml-auto text-[12px] text-muted-foreground">
                {formatDuration(step.duration_ms)}{stepSummary(step) ? ` · ${stepSummary(step)}` : ''}
              </span>
            </button>
            {expanded && (
              <div className="grid grid-cols-1 gap-2 border-t border-border bg-secondary/50 px-3 py-2 md:grid-cols-2">
                <JsonView title="入参" value={step.input} maxHeight={240} />
                <JsonView title="结果" value={step.output} maxHeight={240} />
                <div className="md:col-span-2"><JsonView title="明细" value={step.meta} maxHeight={200} /></div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
