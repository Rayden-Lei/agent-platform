import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import AnswerMarkdown from './AnswerMarkdown'
import ContextCards from './ContextCards'
import ThinkingTrace from './ThinkingTrace'
import ToolList from './ToolList'
import type { ChatCapabilities, Msg } from './types'
import { copyText } from '../../utils/clipboard'
import { formatCost, formatNumber } from '../../utils/format'
import { formatDuration, fromNow } from '../../utils/time'

// 助手消息：不再套气泡，直接平铺在页面上（长回答读起来更舒服）。
// 顺序：头像与名称 → 思考过程（折叠一行）→ 工具调用（细线清单）→ 回答正文 → 引用来源 → 脚注。
// streaming 为 true 且正文为空时展示"思考中…"占位。能看到哪些过程信息由 capabilities 决定（D-19）。
interface Props {
  msg: Msg
  streaming?: boolean
  capabilities: ChatCapabilities
  onShowDetails?: (msg: Msg) => void
  agentName?: string
  onRegenerate?: () => void
}

const ICON = {
  copy: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><rect x="9" y="9" width="12" height="12" rx="2" /><path d="M5 15V5a2 2 0 012-2h10" /></svg>,
  retry: <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1015.5-6.2M21 3v6h-6" /></svg>,
}

// 元信息之间的分隔点：用伪元素级别的独立 span，换行时不会孤零零留在行尾
function Dot() {
  return <span aria-hidden="true" className="select-none opacity-60">·</span>
}

// 脚注上的小按钮：h-6 保证 24px 命中高度，hover 才有底色（不然一行图标按钮看着发灰）
function ToolButton({ label, onClick, icon, accent }: { label: string; onClick: () => void; icon?: ReactNode; accent?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="inline-flex h-6 min-w-6 items-center justify-center gap-1 rounded-md px-1.5 text-[12px] transition-colors hover:bg-accent"
      style={{ color: accent ? 'var(--accent)' : 'var(--fg-muted)' }}
    >
      {icon}
    </button>
  )
}

export default function AssistantMessage({ msg, streaming, capabilities, onShowDetails, agentName = '智枢', onRegenerate }: Props) {
  const hasContent = msg.content.length > 0
  const usageText = capabilities.showUsage && msg.usage?.total_tokens
    ? `${formatNumber(msg.usage.total_tokens)} tokens`
    : ''
  // 输入 / 输出分开只放在 title 里：脚注默认只显示总量，鼠标悬停看明细
  const usageTitle = msg.usage?.total_tokens
    ? `输入 ${formatNumber(msg.usage.prompt_tokens ?? 0)} · 输出 ${formatNumber(msg.usage.completion_tokens ?? 0)}`
    : undefined
  const m = capabilities.showDebugMeta ? msg.metrics : undefined
  const debugText = m
    ? [m.first_token_ms != null ? `首字 ${formatDuration(m.first_token_ms)}` : '', `总 ${formatDuration(m.latency_ms)}`,
      m.retrieval_ms ? `检索 ${formatDuration(m.retrieval_ms)}` : '', m.cost != null ? `成本 ${formatCost(m.cost)}` : ''].filter(Boolean).join(' · ')
    : ''

  return (
    <div className="flex flex-col gap-2 max-w-full">
      {/* 头像与名称：头像取智能体名首字，颜色由主题 accent 决定 */}
      <div className="flex items-center gap-2">
        <span
          className="w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0"
          style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
          aria-hidden="true"
        >
          {agentName.slice(0, 1)}
        </span>
        <span className="text-[11.5px] tracking-wide" style={{ color: 'var(--fg-subtle)' }}>{agentName}</span>
      </div>

      <ThinkingTrace citations={msg.citations} tools={msg.tools} reasoning={msg.reasoning} running={streaming && !hasContent} />
      <ToolList tools={msg.tools} showDetails={capabilities.showToolDetails} />

      {hasContent ? (
        <AnswerMarkdown content={msg.content} citations={capabilities.showCitations ? msg.citations : undefined} />
      ) : streaming ? (
        <div className="text-[13px]" style={{ color: 'var(--fg-subtle)' }}>正在生成回答…</div>
      ) : null}

      {capabilities.showCitations && <ContextCards citations={msg.citations} />}

      {/* 脚注：一行紧凑排列，元信息在前、操作紧跟其后。
          原来用 justify-between 把操作推到容器最右边（回答宽 88%，按钮离正文很远），
          现在不留空白，鼠标从正文滑到按钮的距离更短。
          再往下贴一点（-mt-1.5 抵消外层 gap）：正文与脚注之间只留 2px，不再是 10px 的空白。 */}
      {!streaming && (hasContent || msg.usage) && (
        <div className="-mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11.5px] leading-none" style={{ color: 'var(--fg-subtle)' }}>
          {debugText && <span className="tabular-nums">{debugText}</span>}
          {debugText && usageText && <Dot />}
          {usageText && <span className="tabular-nums" title={usageTitle}>{usageText}</span>}
          {msg.createdAt && (
            <>
              {(debugText || usageText) && <Dot />}
              <span>{fromNow(msg.createdAt)}</span>
            </>
          )}

          <span className="mx-1 h-3 w-px shrink-0" style={{ background: 'var(--border)' }} aria-hidden="true" />

          {capabilities.showDebugMeta && onShowDetails && (msg.trace?.length || msg.prompt) ? (
            <ToolButton label="详情" onClick={() => onShowDetails(msg)} accent />
          ) : null}
          {msg.runId && capabilities.showRunLink && (
            <Link
              to={`/runs/${msg.runId}`}
              className="inline-flex h-6 items-center rounded-md px-1.5 text-[12px] transition-colors hover:bg-accent"
              style={{ color: 'var(--accent)' }}
            >
              运行记录
            </Link>
          )}
          {onRegenerate && (
            <ToolButton label="重新生成" onClick={onRegenerate} icon={ICON.retry} />
          )}
          <ToolButton label="复制回答" onClick={() => copyText(msg.content)} icon={ICON.copy} />
        </div>
      )}
    </div>
  )
}
