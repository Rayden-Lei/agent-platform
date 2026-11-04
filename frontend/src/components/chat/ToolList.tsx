import { useState } from 'react'
import type { ToolStep, ToolStepStatus } from './types'

// 工具调用：一行一个，左侧一条细竖线串起来；点击展开参数与返回结果。
// 不再用彩色 Tag——状态靠圆点与文案表达，入参和结果藏在展开区里。
//
// 图标按"工具类型"给固定几个，不按工具名各自配图：
// 后端 Tool.type 只有 builtin / http 两种，知识库检索是独立步骤。
// 目前 tool_call 事件里不带 type，所以先按名称做启发式，兜底用通用扳手。
interface Props {
  tools?: ToolStep[]
  showDetails: boolean
}

function ToolIcon({ name }: { name: string }) {
  const n = name.toLowerCase()
  const common = { width: 11, height: 11, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const }
  if (n.includes('search') || n.includes('kb') || n.includes('retriev')) {
    return <svg {...common}><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
  }
  if (n.includes('calc') || n.includes('math')) {
    return <svg {...common}><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8M8.5 11.5h.01M12 11.5h.01M15.5 11.5h.01M8.5 15.5h.01M12 15.5h.01M15.5 15.5h.01" /></svg>
  }
  if (n.includes('http') || n.includes('api') || n.includes('fetch')) {
    return <svg {...common}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18" /></svg>
  }
  // 兜底：扳手
  return <svg {...common}><path d="M14.7 6.3a4 4 0 105.3 5.3l-9 9a2.8 2.8 0 11-4-4l9-9a4 4 0 01-1.3-1.3z" /></svg>
}

function statusColor(s: ToolStepStatus) {
  if (s === 'running') return 'var(--accent)'
  if (s === 'error') return '#DC2626'
  return 'var(--fg-subtle)'
}

function statusText(s: ToolStepStatus) {
  if (s === 'running') return '执行中'
  if (s === 'error') return '出错'
  return '完成'
}

function ToolRow({ tool, showDetails }: { tool: ToolStep; showDetails: boolean }) {
  const [open, setOpen] = useState(false)
  const args = tool.args && Object.keys(tool.args).length ? JSON.stringify(tool.args) : ''
  const clickable = showDetails

  return (
    <div>
      <button
        type="button"
        onClick={() => clickable && setOpen((v) => !v)}
        aria-expanded={clickable ? open : undefined}
        className="flex items-center gap-2 w-full text-left min-w-0 text-[12.5px]"
        style={{ cursor: clickable ? 'pointer' : 'default', color: 'var(--fg-muted)' }}
      >
        <span className="shrink-0 flex items-center" style={{ color: 'var(--accent)' }}><ToolIcon name={tool.name} /></span>
        <span className="shrink-0 font-medium" style={{ color: 'var(--fg)' }}>{tool.name}</span>
        {args && (
          <span
            className="truncate"
            style={{ fontFamily: '"SF Mono",Consolas,monospace', fontSize: 11.5, color: 'var(--fg-subtle)' }}
            title={args}
          >
            {args}
          </span>
        )}
        <span className="ml-auto shrink-0 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: statusColor(tool.status) }} />
          <span className="text-[11px]" style={{ color: 'var(--fg-subtle)' }}>{statusText(tool.status)}</span>
        </span>
      </button>

      {open && showDetails && (
        <div className="mt-2 mb-1 ml-5 pl-3" style={{ borderLeft: '1px solid var(--border)' }}>
          <div className="text-[10px] uppercase tracking-[1px] mb-1" style={{ color: 'var(--fg-subtle)' }}>参数</div>
          <pre
            className="m-0 mb-2.5 p-2 rounded-lg text-[11.5px] leading-relaxed overflow-auto whitespace-pre-wrap break-all"
            style={{ background: 'var(--bg-soft-2)', border: '1px solid var(--border)', color: 'var(--fg)', fontFamily: '"SF Mono",Consolas,monospace' }}
          >
            {JSON.stringify(tool.args ?? {}, null, 2)}
          </pre>
          <div className="text-[10px] uppercase tracking-[1px] mb-1" style={{ color: 'var(--fg-subtle)' }}>返回</div>
          <pre
            className="m-0 p-2 rounded-lg text-[11.5px] leading-relaxed overflow-auto whitespace-pre-wrap break-all"
            style={{ background: 'var(--bg-soft-2)', border: '1px solid var(--border)', color: 'var(--fg)', fontFamily: '"SF Mono",Consolas,monospace' }}
          >
            {tool.status === 'running' ? '执行中…' : (tool.result || '（无返回值）')}
          </pre>
        </div>
      )}
    </div>
  )
}

export default function ToolList({ tools, showDetails }: Props) {
  if (!Array.isArray(tools) || tools.length === 0) return null
  return (
    <div className="flex flex-col gap-1.5 self-stretch pl-3" style={{ borderLeft: '1.5px solid var(--border-strong)', marginLeft: 1 }}>
      {tools.map((t, i) => <ToolRow key={t.id ?? `${t.name}-${i}`} tool={t} showDetails={showDetails} />)}
    </div>
  )
}
