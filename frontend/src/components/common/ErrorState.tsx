import { Alert, Button, Result } from 'antd'

// 加载失败占位：toast 消失后界面仍能看出出过错，并给"重试"。compact 用在卡片 / 抽屉内。
interface Props {
  message?: string | null
  onRetry?: () => void
  compact?: boolean
}

export default function ErrorState({ message = '加载失败', onRetry, compact = false }: Props) {
  if (compact) {
    return <Alert type="error" showIcon message={message} action={onRetry && <Button size="small" onClick={onRetry}>重试</Button>} />
  }
  return <Result status="error" title="加载失败" subTitle={message} extra={onRetry && <Button type="primary" onClick={onRetry}>重试</Button>} />
}
