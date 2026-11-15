import { useState, type ReactNode } from 'react'
import type { ConversationRow } from '../../api'
import { fromNow } from '../../utils/time'
import InlineConfirm from '../ui/InlineConfirm'

// 会话列表：搜索 + 新建 + 按更新时间倒序；当前会话高亮，悬停出现删除。
// 改造后改为自绘列表（原实现用 antd List），不再有内建分页，改为"加载更多"。
interface Props {
  conversations: ConversationRow[]
  total: number
  currentId: number | null
  q?: string
  onSearch: (q?: string) => void
  onSelect: (id: number) => void
  onNew: () => void
  onLoadMore: () => void
  onDelete: (id: number) => void
  agentSelector?: ReactNode
  /** 列表加载失败的原因。非空时显示错误态与重试入口，而不是"还没有会话"——
   *  接口 500 时显示空态会让用户以为历史会话被清空了（docs/07 第 3 节：三态互斥）。 */
  error?: string | null
  loading?: boolean
  onRetry?: () => void
}

export default function ConversationList({ conversations, total, currentId, q, onSearch, onSelect, onNew, onLoadMore, onDelete, agentSelector, error, loading, onRetry }: Props) {
  const [keyword, setKeyword] = useState(q ?? '')

  return (
    <div className="flex flex-col h-full min-h-0 gap-2.5">
      {agentSelector}

      <div className="flex items-center gap-1.5">
        <input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') onSearch(keyword || undefined) }}
          placeholder="搜索会话…"
          className="flex-1 min-w-0 h-8 px-2.5 rounded-lg text-[12.5px] outline-none"
          style={{ background: 'var(--bg-soft-2)', border: '1px solid var(--border)', color: 'var(--fg)' }}
        />
        <button
          type="button"
          onClick={onNew}
          title="新建会话"
          aria-label="新建会话"
          className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
          style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto flex flex-col gap-0.5 min-h-0">
        {/* 三态互斥：错误 > 加载中 > 空。错误优先，否则接口挂了会被误读成"没有会话" */}
        {error ? (
          <div className="py-6 px-2 text-center">
            <p className="m-0 text-[12.5px]" style={{ color: 'var(--danger, #d4380d)' }}>{error}</p>
            {onRetry && (
              <button type="button" onClick={onRetry} className="mt-1.5 text-[12px] underline" style={{ color: 'var(--accent)' }}>
                重试
              </button>
            )}
          </div>
        ) : loading && conversations.length === 0 ? (
          <div className="text-[12.5px] py-6 text-center" style={{ color: 'var(--fg-subtle)' }}>加载中…</div>
        ) : conversations.length === 0 ? (
          <div className="text-[12.5px] py-6 text-center" style={{ color: 'var(--fg-subtle)' }}>还没有会话</div>
        ) : null}
        {conversations.map((c) => {
          const active = c.id === currentId
          return (
            <div
              key={c.id}
              role="button"
              tabIndex={0}
              onClick={() => onSelect(c.id)}
              onKeyDown={(e) => { if (e.key === 'Enter') onSelect(c.id) }}
              className="group flex shrink-0 items-center gap-2 px-2.5 py-2 rounded-lg cursor-pointer text-[12.5px]"
              style={{
                background: active ? 'var(--accent-soft)' : 'transparent',
                color: active ? 'var(--fg)' : 'var(--fg-muted)',
              }}
            >
              <div className="min-w-0 flex-1">
                <div className="truncate" style={{ fontWeight: active ? 550 : 400 }}>{c.title || '未命名会话'}</div>
                <div className="text-[11px]" style={{ color: 'var(--fg-subtle)' }}>{fromNow(c.updated_at)}</div>
              </div>
              {/* 二次确认：删除会话会连带删掉整段对话记录，误点代价高。
                  全站其他删除都走 InlineConfirm，这里之前是点一下就删（2026-11-08 修）。 */}
              <InlineConfirm
                message={`确定删除会话「${c.title || '未命名会话'}」？这条会话的全部消息与运行记录都会被删除。`}
                confirmLabel="删除"
                danger
                onConfirm={() => onDelete(c.id)}
              >
                <button
                  type="button"
                  title="删除会话"
                  aria-label="删除会话"
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded shrink-0 relative after:absolute after:-inset-2 after:content-['']"
                  style={{ color: 'var(--danger, #DC2626)' }}
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" /></svg>
                </button>
              </InlineConfirm>
            </div>
          )
        })}
        {conversations.length < total && (
          <button type="button" onClick={onLoadMore} className="text-[12px] py-2 rounded-lg" style={{ color: 'var(--accent)' }}>
            加载更多（{conversations.length}/{total}）
          </button>
        )}
      </div>
    </div>
  )
}
