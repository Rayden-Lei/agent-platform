import { Button, Tag, Tooltip, Typography } from 'antd'
import { MessageOutlined, PlusOutlined } from '@ant-design/icons'

// 分享访客页对话面板的头部：会话抽屉入口、智能体名称与简介、"内容由 AI 生成"、新对话。
interface Props {
  name: string
  description?: string | null
  onOpenList: () => void
  onNew: () => void
}

export default function ShareHeader({ name, description, onOpenList, onNew }: Props) {
  return (
    <>
      <Tooltip title="我的会话"><Button size="small" icon={<MessageOutlined />} onClick={onOpenList} aria-label="我的会话" /></Tooltip>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Typography.Text strong ellipsis style={{ display: 'block' }}>{name}</Typography.Text>
        {description && <Typography.Text type="secondary" ellipsis style={{ display: 'block', fontSize: 12 }}>{description}</Typography.Text>}
      </div>
      <Tag style={{ marginInlineEnd: 0 }}>内容由 AI 生成</Tag>
      <Tooltip title="新对话"><Button size="small" icon={<PlusOutlined />} onClick={onNew} aria-label="新对话" /></Tooltip>
    </>
  )
}
