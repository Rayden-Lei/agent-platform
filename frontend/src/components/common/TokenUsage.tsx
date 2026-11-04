import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { formatCost, formatNumber } from '../../utils/format'

// Token 用量：紧凑版只显示总量（Tooltip 给拆分），完整版显示输入 / 输出 / 合计 / 成本。
interface Usage { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
interface Props {
  usage?: Usage | null
  cost?: number | null
  compact?: boolean
}

export default function TokenUsage({ usage, cost, compact = false }: Props) {
  if (!usage || !usage.total_tokens) return <span className="text-muted-foreground">-</span>
  const detail = `输入 ${formatNumber(usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(usage.completion_tokens ?? 0)}`
  if (compact) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span>{formatNumber(usage.total_tokens)}</span>
        </TooltipTrigger>
        <TooltipContent>{detail + (cost !== null && cost !== undefined ? `，成本 ${formatCost(cost)}` : '')}</TooltipContent>
      </Tooltip>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-4">
      <span>输入 <b>{formatNumber(usage.prompt_tokens ?? 0)}</b></span>
      <span>输出 <b>{formatNumber(usage.completion_tokens ?? 0)}</b></span>
      <span>合计 <b>{formatNumber(usage.total_tokens)}</b></span>
      {cost !== null && cost !== undefined && <span>成本 <b>{formatCost(cost)}</b></span>}
    </div>
  )
}
