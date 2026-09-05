import { useState } from 'react'
import { Button, Space, Typography, message } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

// JSON / 长文本展示：缩进、复制、超高折叠；取代散落的 <pre>{JSON.stringify(...)}</pre>。
interface Props {
  value: unknown
  maxHeight?: number
  title?: string
}

function toText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') {
    // 字符串本身可能是 JSON（节点日志的输入输出快照），能解析就格式化
    try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
  }
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

export default function JsonView({ value, maxHeight = 240, title }: Props) {
  const [expanded, setExpanded] = useState(false)
  const text = toText(value)
  if (!text) return <Typography.Text type="secondary">（空）</Typography.Text>
  const long = text.split('\n').length > 12 || text.length > 800
  const copy = () => navigator.clipboard?.writeText(text).then(() => message.success('已复制'))
  return (
    <div className="json-view">
      <div className="json-view-bar">
        <span style={{ fontSize: 12, color: '#6b7280' }}>{title}</span>
        <Space size={4}>
          {long && <Button size="small" type="link" onClick={() => setExpanded(!expanded)}>{expanded ? '收起' : '展开'}</Button>}
          <Button size="small" type="text" icon={<CopyOutlined />} onClick={copy} />
        </Space>
      </div>
      <pre style={{ maxHeight: expanded ? undefined : maxHeight }}>{text}</pre>
    </div>
  )
}
