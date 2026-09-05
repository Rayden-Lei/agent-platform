import { useRef, useState } from 'react'
import { message } from 'antd'
import { chatAgentStream } from '../../api'
import type { Msg } from './types'

// 对话发送的状态机：追加占位消息 → SSE 流式 patch 最后一条 assistant → 结束后回传会话 id；支持停止与重新生成。
interface Options {
  agentId?: number
  conversationId: number | null
  onConversationCreated: (id: number) => void
}

export function useChatStream(messages: Msg[], setMessages: React.Dispatch<React.SetStateAction<Msg[]>>, { agentId, conversationId, onConversationCreated }: Options) {
  const [sending, setSending] = useState(false)
  // 当前流式请求的 AbortController："停止"按钮通过它中断整个 SSE 流
  const abortRef = useRef<AbortController | null>(null)

  // 更新流式过程中最后一条 assistant 消息（浅拷贝后原地修改，保持不可变更新语义）
  const patchLast = (fn: (last: Msg) => void) => {
    setMessages((prev) => {
      if (prev.length === 0) return prev
      const next = [...prev]
      const last = { ...next[next.length - 1] }
      fn(last)
      next[next.length - 1] = last
      return next
    })
  }

  // 核心发送逻辑：msg 为本次输入，isRegen 表示"重新生成"（基于上一条用户消息重发）
  const doSend = async (msg: string, isRegen: boolean) => {
    if (!msg || !agentId || sending) return
    if (isRegen) {
      // 重新生成：弹掉最后一条 assistant（上次的回答），再补一条新的空占位
      setMessages((prev) => { const next = [...prev]; next.pop(); next.push({ role: 'assistant', content: '' }); return next })
    } else {
      setMessages((prev) => [...prev, { role: 'user', content: msg, createdAt: new Date().toISOString() }, { role: 'assistant', content: '' }])
    }
    setSending(true)
    const controller = new AbortController()
    abortRef.current = controller
    try {
      const newCid = await chatAgentStream(agentId, { message: msg, conversation_id: conversationId }, {
        onCitations: (citations) => patchLast((last) => { last.citations = citations }),
        onDelta: (content) => patchLast((last) => { last.content += content }),
        onToolCall: (tc) => patchLast((last) => {
          last.tools = [...(last.tools || []), { id: tc.id, name: tc.name || '工具', args: tc.arguments ?? {}, status: 'running' as const }]
        }),
        // 工具结果返回：优先按 tool_call_id 精确匹配，匹配不到回退到第一条仍 running 的步骤
        onToolResult: (tr) => patchLast((last) => {
          const tools = last.tools || []
          let idx = tools.findIndex((t) => t.id && tr.tool_call_id && t.id === tr.tool_call_id)
          if (idx < 0) idx = tools.findIndex((t) => t.status === 'running')
          if (idx >= 0) {
            const next = tools.slice()
            next[idx] = { ...next[idx], status: 'done' as const, result: tr.content }
            last.tools = next
          }
        }),
        onError: (errMsg) => patchLast((last) => { last.content += '\n[错误] ' + errMsg }),
        // 流结束：附带 token 用量、运行记录 id（可跳详情）与消息 id
        onDone: (evt) => patchLast((last) => { if (evt.usage) last.usage = evt.usage; last.runId = evt.run_id; last.id = evt.message_id; last.createdAt = new Date().toISOString() }),
      }, controller.signal)
      if (newCid && newCid !== conversationId) onConversationCreated(newCid)
    } catch (e) {
      // 主动停止产生 AbortError，属预期行为，静默返回不提示错误
      if ((e as { name?: string }).name === 'AbortError') return
      message.error((e as Error).message || '发送失败')
    } finally {
      setSending(false)
      abortRef.current = null
    }
  }

  const stop = () => abortRef.current?.abort()
  const regenerate = () => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (lastUser) doSend(lastUser.content, true)
  }
  return { sending, send: (text: string) => doSend(text, false), stop, regenerate }
}
