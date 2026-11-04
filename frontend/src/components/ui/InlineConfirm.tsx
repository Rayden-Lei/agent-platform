import type { ReactNode } from 'react'
import { confirm } from './confirm'

// 行内二次确认：替代 antd Popconfirm。点击后弹全局确认框（<ConfirmHost /> 挂在根部），
// 不再在按钮旁边挤一行「确认? 确定 取消」——那一行会把操作区的按钮挤变形。
interface Props {
  message: string
  onConfirm: () => void
  children: ReactNode
  confirmLabel?: string
  danger?: boolean
}

// 文案里第一个「？」之前当标题，之后当说明：
// 「确定删除该用户？其创建的资源保留但创建人置空」拆成标题 + 说明；没有问号的整段当标题。
function split(message: string): { title: string; content?: string } {
  const i = message.indexOf('？')
  if (i < 0) return { title: message }
  const rest = message.slice(i + 1).trim()
  return rest ? { title: message.slice(0, i + 1), content: rest } : { title: message }
}

export default function InlineConfirm({ message, onConfirm, children, confirmLabel = '确认', danger = false }: Props) {
  const ask = () => {
    const { title, content } = split(message)
    void confirm({ title, content, okText: confirmLabel, danger }).then((ok) => { if (ok) onConfirm() })
  }
  return (
    <span onClick={(e) => { e.stopPropagation(); ask() }} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') ask() }}>
      {children}
    </span>
  )
}
