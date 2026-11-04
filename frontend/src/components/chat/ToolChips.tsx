// 工具调用标签条：每个工具一个徽章（点击展开参数/结果详情），颜色与图标随执行状态变化
import { Loader2, Wrench } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import Badge from '../ui/Badge'
import type { ToolStep, ToolStepStatus } from './types'

// 工具步骤状态 → 徽章语义色：运行中 info、出错 danger、其余 success
function tone(status: ToolStepStatus): 'info' | 'danger' | 'success' {
  if (status === 'running') return 'info'
  if (status === 'error') return 'danger'
  return 'success'
}

// 工具详情的悬浮内容：格式化展示调用参数与返回结果
function ToolDetail({ tool }: { tool: ToolStep }) {
  return (
    <div className="max-w-[380px] min-w-[260px]">
      <div className="mb-2">
        <span className="text-[12px] text-muted-foreground">参数</span>
        <pre className="tool-detail-pre">{JSON.stringify(tool.args ?? {}, null, 2)}</pre>
      </div>
      <div>
        <span className="text-[12px] text-muted-foreground">结果</span>
        <div className="tool-detail-result">
          {tool.status === 'running' ? '执行中…' : (tool.result || '（无返回值）')}
        </div>
      </div>
    </div>
  )
}

// 徽章本体：图标 + 工具名，图标随状态换成转圈或扳手
function Chip({ tool }: { tool: ToolStep }) {
  return (
    <Badge tone={tone(tool.status)} title={tool.name}>
      <span className="inline-flex items-center gap-1">
        {tool.status === 'running'
          ? <Loader2 className="size-3.5 animate-spin" />
          : <Wrench className="size-3.5" />}
        {tool.name}
      </span>
    </Badge>
  )
}

// 主组件：无工具调用时不渲染；showDetails 时每个徽章点击后以 Popover 展示该步骤的参数与结果，
// 否则只显示工具名（调用者不看工具入参：可能含内部地址，docs/15 D-19）
export default function ToolChips({ tools, showDetails }: { tools?: ToolStep[]; showDetails: boolean }) {
  if (!Array.isArray(tools) || tools.length === 0) return null

  return (
    <div className="tool-chips flex flex-wrap items-center gap-1.5">
      {tools.map((t, i) => (showDetails ? (
        <Popover key={i}>
          <PopoverTrigger asChild>
            <button type="button" className="tool-chip cursor-pointer border-0 bg-transparent p-0" aria-label={`查看工具 ${t.name} 的参数与结果`}>
              <Chip tool={t} />
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-auto p-3">
            <div className="mb-1.5 text-[13px] font-medium">{t.name}</div>
            <ToolDetail tool={t} />
          </PopoverContent>
        </Popover>
      ) : <Chip key={i} tool={t} />))}
    </div>
  )
}
