import { Inbox } from 'lucide-react'
import Button from '../ui/Button'

// 空态：说明"为什么空"与"下一步能做什么"（docs/07 第 4 节），不只一句"暂无数据"。
interface Props {
  description: React.ReactNode
  action?: { label: string; onClick: () => void }
  /** 兼容旧参数：simple 用小图标，default 也用同一套（统一视觉） */
  image?: 'default' | 'simple'
}

export default function EmptyState({ description, action }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-10">
      <Inbox className="size-8 text-muted-foreground/50" aria-hidden="true" />
      <div className="max-w-md text-center text-[14px] leading-relaxed text-muted-foreground">{description}</div>
      {action && <Button variant="primary" size="sm" onClick={action.onClick}>{action.label}</Button>}
    </div>
  )
}
