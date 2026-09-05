import { Tag } from 'antd'
import { STATUS, type StatusDomain } from '../../constants/status'

// 全站状态标签：文案与语义色来自 constants/status，未知值原样上屏（灰色），不再各页面写英文裸值。
interface Props {
  domain: StatusDomain
  value: string | boolean | null | undefined
  style?: React.CSSProperties
}

export default function StatusTag({ domain, value, style }: Props) {
  if (value === null || value === undefined || value === '') return <span style={{ color: '#9ca3af' }}>-</span>
  const meta = STATUS[domain][String(value)]
  return <Tag color={meta?.color ?? 'default'} style={{ marginInlineEnd: 0, ...style }}>{meta?.label ?? String(value)}</Tag>
}
