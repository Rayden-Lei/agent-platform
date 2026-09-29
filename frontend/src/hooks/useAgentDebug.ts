import { useCallback, useRef, useState } from 'react'
import { chatDebugStream, type AgentInput, type ChatTransport, type DebugHistoryItem } from '../api'
import { useChatStream } from '../components/chat/useChatStream'
import type { Msg } from '../components/chat/types'

// 装配页调试的状态与请求（docs/15 3.4）：每轮把编辑器当前内容（含未保存修改）作为内联配置发出去，调试历史只在页面内存里，
// 不进会话列表。发送状态机复用 useChatStream，这里只管"带哪些历史"和"重新生成"的语义。
const DEBUG_HISTORY_MAX_ITEMS = 40 // 与后端 debug-chat 的上限一致（条数、总字数），超出从最早的一问一答开始丢
const DEBUG_HISTORY_MAX_CHARS = 64000

// 只带完整的一问一答：以错误结束或没有回答的那一轮不带给下一轮，否则模型会看到一句"[错误] …"当成自己的回答
function toHistory(messages: Msg[]): DebugHistoryItem[] {
  const out: DebugHistoryItem[] = []
  let i = 0
  while (i + 1 < messages.length) {
    const question = messages[i]
    const answer = messages[i + 1]
    if (question.role !== 'user' || answer.role !== 'assistant') { i += 1; continue }
    if (!answer.failed && answer.content) out.push({ role: 'user', content: question.content }, { role: 'assistant', content: answer.content })
    i += 2
  }
  const chars = () => out.reduce((sum, h) => sum + h.content.length, 0)
  while (out.length > DEBUG_HISTORY_MAX_ITEMS || chars() > DEBUG_HISTORY_MAX_CHARS) out.splice(0, 2)
  return out
}

export function useAgentDebug(agentId: number, getConfig: () => AgentInput) {
  const [messages, setMessages] = useState<Msg[]>([])
  const messagesRef = useRef(messages)
  messagesRef.current = messages
  const configRef = useRef(getConfig)
  configRef.current = getConfig
  // 本轮要带的历史在发送前算好：发送时消息列表已追加了本轮的提问与占位回答
  const historyRef = useRef<DebugHistoryItem[]>([])
  const transport = useCallback<ChatTransport>((payload, handlers, signal) => chatDebugStream(agentId, {
    message: payload.message, history: historyRef.current, config_source: 'inline', config: configRef.current(),
  }, handlers, signal), [agentId])
  const chat = useChatStream(messages, setMessages, { transport, conversationId: null, onConversationCreated: () => undefined })

  const send = (text: string) => {
    historyRef.current = toHistory(messagesRef.current)
    chat.send(text)
  }
  // 重新生成 = 去掉最后一问一答、用之前的历史重发同一个问题（不照搬线上"再追加一条相同的提问"）
  const regenerate = () => {
    const current = messagesRef.current
    const idx = current.map((m) => m.role).lastIndexOf('user')
    if (idx < 0 || chat.sending) return
    historyRef.current = toHistory(current.slice(0, idx))
    setMessages((prev) => prev.slice(0, idx))
    chat.send(current[idx].content)
  }
  const clear = () => { chat.stop(); setMessages([]) }
  return { messages, sending: chat.sending, send, stop: chat.stop, regenerate, clear }
}
