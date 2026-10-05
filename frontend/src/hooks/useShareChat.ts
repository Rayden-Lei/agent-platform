import { useCallback, useEffect, useMemo, useState } from 'react'
import { message } from 'antd'
import { RequestError, chatShareStream, deleteShareConversation, listShareConversations, listShareMessages, type ChatTransport, type ConversationRow } from '../api'
import { useChatStream } from '../components/chat/useChatStream'
import { toGuestChatMessages } from '../components/chat/messages'
import type { Msg } from '../components/chat/types'

const PAGE = 50

// 分享访客页的会话与对话（docs/15 3.6）：本访客自己的会话列表（标题搜索、加载更多、删除）、切换会话取历史、SSE 发送。
// 任何访客请求 401 都交给 onUnauthorized（回到进入流程）；ready 为假时不取数、不发送。
export function useShareChat(code: string, ready: boolean, onUnauthorized: (detail?: string) => void) {
  const [conversations, setConversations] = useState<ConversationRow[]>([])
  const [total, setTotal] = useState(0)
  const [q, setQ] = useState<string | undefined>()
  const [conversationId, setConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Msg[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)

  const handleError = useCallback((e: unknown, fallback: string) => {
    if (e instanceof RequestError && e.status === 401) onUnauthorized(e.message)
    else message.error((e as Error).message || fallback)
  }, [onUnauthorized])

  const loadConversations = useCallback(async (page = 1) => {
    if (!ready) return
    try {
      const res = await listShareConversations(code, page, PAGE, q)
      // 会话侧栏与登录对话页共用，访客的会话没有智能体与摘要字段
      const rows = res.items.map((c): ConversationRow => ({ ...c, agent_id: null, agent_name: null, summary: null }))
      setConversations((prev) => (page === 1 ? rows : [...prev, ...rows]))
      setTotal(res.total)
    } catch (e) { handleError(e, '加载会话失败') }
  }, [code, ready, q, handleError])
  useEffect(() => { loadConversations(1) }, [loadConversations])
  // 重新进入后可能是另一个访客身份（改了密码、重置了链接）：旧会话不一定还属于自己，清掉
  useEffect(() => { if (!ready) { setConversationId(null); setConversations([]); setTotal(0) } }, [ready])

  // 切换会话：先清空再取历史，切走时丢弃过期的响应
  useEffect(() => {
    if (!ready || !conversationId) { setMessages([]); return }
    let cancelled = false
    setMessages([])
    setLoadingMessages(true)
    listShareMessages(code, conversationId)
      .then((rows) => { if (!cancelled) setMessages(toGuestChatMessages(rows)) })
      .catch((e) => { if (!cancelled) handleError(e, '加载历史失败') })
      .finally(() => { if (!cancelled) setLoadingMessages(false) })
    return () => { cancelled = true }
  }, [code, ready, conversationId, handleError])

  const transport = useMemo<ChatTransport | undefined>(
    () => (ready ? (payload, handlers, signal) => chatShareStream(code, payload, handlers, signal, onUnauthorized) : undefined),
    [code, ready, onUnauthorized],
  )
  const stream = useChatStream(messages, setMessages, {
    transport, conversationId,
    onConversationCreated: (id) => { setConversationId(id); loadConversations(1) },
  })

  const newConversation = () => { setConversationId(null); setMessages([]) }
  // 删除失败由会话侧栏提示（ConversationList 捕获）；401 先回到进入流程
  const removeConversation = async (id: number) => {
    try {
      await deleteShareConversation(code, id)
    } catch (e) {
      if (e instanceof RequestError && e.status === 401) onUnauthorized(e.message)
      throw e
    }
    if (conversationId === id) newConversation()
    loadConversations(1)
  }
  const loadMore = () => loadConversations(Math.floor(conversations.length / PAGE) + 1)

  return { conversations, total, q, setQ, conversationId, setConversationId, messages, loadingMessages, stream, newConversation, removeConversation, loadMore }
}
