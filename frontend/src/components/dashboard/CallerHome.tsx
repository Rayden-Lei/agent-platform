import { Bot, MessageSquare } from 'lucide-react'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { AgentBrief, ConversationRow } from '../../api'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import { fromNow } from '../../utils/time'

// 调用者的工作台（docs/15 AG-05）：能对话的智能体卡片 + 本人最近的会话。调用者看不了运营统计，
// 此前工作台照样请求 /stats/* 拿 3 个 403、页面只剩横幅。数据由工作台页面取好传入，本组件不发请求。
interface Props {
  agents: AgentBrief[] | null // 只取第一页（OPTIONS_PAGE，100 个）
  agentsTotal?: number // 可对话智能体总数；超过已取的数量时提示去对话页搜索
  conversations: ConversationRow[] | null
  agentsError?: string | null
  conversationsError?: string | null
  onRetry: () => void
  onOpenAgent: (agent: AgentBrief) => void
  onOpenConversation: (conversation: ConversationRow) => void
}

// 加载占位：与真实卡片同尺寸，避免数据回来时整块跳动
function AgentSkeleton() {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-3">
      <Skeleton className="h-4 w-24" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-2/3" />
    </div>
  )
}

export default function CallerHome({ agents, agentsTotal, conversations, agentsError, conversationsError, onRetry, onOpenAgent, onOpenConversation }: Props) {
  const total = agentsTotal ?? agents?.length
  const partial = !!agents && total !== undefined && total > agents.length
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <section className="flex flex-col rounded-xl border border-border bg-card lg:col-span-2">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
          <h3 className="m-0 text-[13px] font-semibold text-foreground">可以对话的智能体{total !== undefined ? `（${total}）` : ''}</h3>
          {partial && <span className="text-[12px] text-muted-foreground">这里显示前 {agents.length} 个，其余在对话页搜索</span>}
        </div>

        <div className="min-h-0 flex-1 p-3">
          {agentsError ? (
            <ErrorState compact message={agentsError} onRetry={onRetry} />
          ) : !agents ? (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{[0, 1, 2].map((i) => <AgentSkeleton key={i} />)}</div>
          ) : agents.length === 0 ? (
            <EmptyState description="管理员还没有发布可用的智能体；发布后会出现在这里" />
          ) : (
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {agents.map((a) => (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onOpenAgent(a)}
                  className="flex flex-col items-start gap-1.5 rounded-lg border border-border p-3 text-left transition-colors hover:border-border-strong hover:bg-accent/50"
                >
                  <span className="flex w-full items-center gap-1.5 text-[13.5px] font-semibold text-foreground">
                    <Bot className="size-4 shrink-0 text-primary" aria-hidden="true" />
                    <span className="truncate">{a.name}</span>
                  </span>
                  <span className="line-clamp-2 min-h-10 w-full text-[13px] leading-snug text-muted-foreground">{a.description || '没有简介'}</span>
                  <span className="text-[12px] text-muted-foreground">{a.published_at ? `${fromNow(a.published_at)}发布` : ''}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <section className="flex flex-col rounded-xl border border-border bg-card">
        <div className="border-b border-border px-3.5 py-2.5">
          <h3 className="m-0 text-[13px] font-semibold text-foreground">最近的会话</h3>
        </div>

        <div className="min-h-0 flex-1 p-3">
          {conversationsError ? (
            <ErrorState compact message={conversationsError} onRetry={onRetry} />
          ) : !conversations ? (
            <div className="flex flex-col gap-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
          ) : conversations.length === 0 ? (
            <EmptyState description="还没有会话；选一个智能体开始吧" />
          ) : (
            <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
              {conversations.map((c) => (
                <li key={c.id}>
                  <button
                    type="button"
                    onClick={() => onOpenConversation(c)}
                    className="flex w-full items-start gap-2 rounded-lg px-1.5 py-2 text-left transition-colors hover:bg-accent/50"
                  >
                    <MessageSquare className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[13.5px] text-foreground">{c.title || '未命名会话'}</span>
                      <span className="block truncate text-[12px] text-muted-foreground">{c.agent_name || '已删除的智能体'} · {fromNow(c.updated_at)}</span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  )
}
