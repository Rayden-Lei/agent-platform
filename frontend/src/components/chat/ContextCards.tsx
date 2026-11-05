import type { Citation } from './types'

// 引用来源：回答下方按命中顺序列出知识片段，点标题看全文。
// 改造后改为自绘卡片，不再用 antd Card；相关度用百分比展示，比原始 score 好读。
interface Props {
  citations?: Citation[]
}

export default function ContextCards({ citations }: Props) {
  if (!Array.isArray(citations) || citations.length === 0) return null
  return (
    <div className="flex flex-col gap-1.5 self-stretch">
      <div className="flex items-center gap-1.5 text-[11.5px]" style={{ color: 'var(--fg-subtle)' }}>
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 19.5A2.5 2.5 0 016.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" />
        </svg>
        引用来源 {citations.length} 条
      </div>
      {citations.map((c, i) => (
        <details
          key={c.chunk_id ?? i}
          className="rounded-lg overflow-hidden"
          style={{ background: 'var(--bg-soft-2)', border: '1px solid var(--border)' }}
        >
          <summary
            className="flex items-center gap-2 px-3 py-2 cursor-pointer text-[12.5px]"
            style={{ color: 'var(--fg)' }}
          >
            <span className="shrink-0 font-semibold" style={{ color: 'var(--accent)' }}>[{i + 1}]</span>
            <span className="truncate">{c.doc_name || '未命名片段'}</span>
            {typeof c.score === 'number' && (
              <span className="ml-auto shrink-0 text-[11px]" style={{ color: 'var(--fg-subtle)', fontVariantNumeric: 'tabular-nums' }}>
                {(c.score * 100).toFixed(0)}%
              </span>
            )}
          </summary>
          <div className="px-3 pb-2.5 text-[12.5px] leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--fg-muted)' }}>
            {c.content || '（无内容）'}
          </div>
        </details>
      ))}
    </div>
  )
}
