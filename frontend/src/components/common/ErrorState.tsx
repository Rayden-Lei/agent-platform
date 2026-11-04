import { CircleAlert, RefreshCw } from 'lucide-react'
import Button from '../ui/Button'

// 加载失败占位：toast 消失后界面仍能看出出过错，并给"重试"。compact 用在卡片 / 抽屉内。
interface Props {
  message?: string | null
  onRetry?: () => void
  compact?: boolean
}

export default function ErrorState({ message = '加载失败', onRetry, compact = false }: Props) {
  if (compact) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
        <CircleAlert className="size-3.5 shrink-0 text-destructive" />
        <span className="min-w-0 flex-1 text-[13px] text-destructive">{message}</span>
        {onRetry && <Button size="sm" variant="ghost" icon={<RefreshCw />} onClick={onRetry}>重试</Button>}
      </div>
    )
  }
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 py-16">
      <CircleAlert className="size-8 text-destructive" />
      <div className="text-[14px] font-semibold">加载失败</div>
      <div className="max-w-md text-center text-[13px] text-muted-foreground">{message}</div>
      {onRetry && <Button variant="primary" size="md" icon={<RefreshCw />} onClick={onRetry}>重试</Button>}
    </div>
  )
}
