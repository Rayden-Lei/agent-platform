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

export default function AssistantMessage({ msg, streaming, capabilities, onShowDetails, agentName = '智枢', onRegenerate }: Props) {
  const hasContent = msg.content.length > 0
  const usageText = capabilities.showUsage && msg.usage?.total_tokens
    ? `Token ${formatNumber(msg.usage.total_tokens)}（输入 ${formatNumber(msg.usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(msg.usage.completion_tokens ?? 0)}）`
    : ''
  const m = capabilities.showDebugMeta ? msg.metrics : undefined
  const debugText = m
    ? [m.first_token_ms != null ? `首字 ${formatDuration(m.first_token_ms)}` : '', `总 ${formatDuration(m.latency_ms)}`,
      m.retrieval_ms ? `检索 ${formatDuration(m.retrieval_ms)}` : '', m.cost != null ? `成本 ${formatCost(m.cost)}` : ''].filter(Boolean).join(' · ')
    : ''

  return (
    <div className="flex flex-col gap-2.5 max-w-full">
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

      {!streaming && (hasContent || msg.usage) && (
        <div className="flex items-center justify-between gap-3 flex-wrap pt-0.5">
          <span className="text-[12px] leading-relaxed" style={{ color: 'var(--fg-subtle)' }}>
            {debugText && <>{debugText}<br /></>}
            {usageText}
            {msg.createdAt ? `${usageText ? ' · ' : ''}${fromNow(msg.createdAt)}` : ''}
          </span>
          <span className="flex items-center gap-1">
            {capabilities.showDebugMeta && onShowDetails && (msg.trace?.length || msg.prompt) && (
              <button type="button" onClick={() => onShowDetails(msg)} className="text-[12px] px-1.5 py-1 rounded" style={{ color: 'var(--accent)' }}>详情</button>
            )}
            {msg.runId && capabilities.showRunLink && (
              <Link to={`/runs/${msg.runId}`} className="text-[12px] px-1.5 py-1 rounded hover:underline" style={{ color: 'var(--accent)' }}>运行记录</Link>
            )}
            {onRegenerate && (
              <button type="button" onClick={onRegenerate} className="p-1.5 rounded-lg" style={{ color: 'var(--fg-muted)' }} title="重新生成" aria-label="重新生成">{ICON.retry}</button>
            )}
            <button type="button" onClick={() => copyText(msg.content)} className="p-1.5 rounded-lg" style={{ color: 'var(--fg-muted)' }} title="复制回答" aria-label="复制回答">{ICON.copy}</button>
          </span>
        </div>
      )}
    </div>
  )
}
