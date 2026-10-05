import type { GuestMessage, MessageRow } from '../../api'
import type { Msg, ToolStep } from './types'

// 分享访客的历史消息（访客口径：引用只有文档名与内容，工具只有名称）→ 对话面板的消息结构
export function toGuestChatMessages(rows: GuestMessage[]): Msg[] {
  return rows.map((m): Msg => ({
    id: m.id, role: m.role as Msg['role'], content: m.content, citations: m.citations, createdAt: m.created_at,
    tools: m.tool_names.map((name): ToolStep => ({ name, args: {}, status: 'done' })),
  }))
}

// 接口返回的历史消息 → 对话面板的消息结构（tool_calls → tools、token_usage → usage）。
// 登录对话页加载历史用它；工具调用记录的参数键历史上有 args / arguments 两种写法，这里统一
export function toChatMessages(rows: MessageRow[]): Msg[] {
  return rows.map((m): Msg => ({
    id: m.id, role: m.role as Msg['role'], content: m.content, citations: (m.citations as Msg['citations']) || [],
    tools: ((m.tool_calls || []) as Array<{ id?: string; name: string; args?: unknown; arguments?: unknown; result?: string }>)
      .map((t): ToolStep => ({ id: t.id, name: t.name, args: t.args ?? t.arguments ?? {}, status: 'done', result: t.result })),
    usage: m.token_usage || undefined, createdAt: m.created_at,
  }))
}
