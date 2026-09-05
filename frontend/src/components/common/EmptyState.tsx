import { Button, Empty } from 'antd'

// 空态：说明"为什么空"与"下一步能做什么"（docs/07 第 4 节），不只一句"暂无数据"。
interface Props {
  description: React.ReactNode
  action?: { label: string; onClick: () => void }
  image?: 'default' | 'simple'
}

export default function EmptyState({ description, action, image = 'simple' }: Props) {
  return (
    <Empty image={image === 'simple' ? Empty.PRESENTED_IMAGE_SIMPLE : undefined} description={description} style={{ margin: '24px 0' }}>
      {action && <Button type="primary" size="small" onClick={action.onClick}>{action.label}</Button>}
    </Empty>
  )
}
