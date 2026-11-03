import type { CSSProperties } from 'react'
import { STATUS, type StatusDomain } from '../../constants/status'
import Badge from '../ui/Badge'

// 全站状态标签：文案与语义色来自 constants/status，未知值原样上屏（灰色），不再各页面写英文裸值。
// 迁移期改为自绘 Badge（原实现用 antd Tag），props 保持兼容，调用方不用改。
interface Props {
  domain: StatusDomain
  value: string | boolean | null | undefined
  style?: CSSProperties
}

export default function StatusTag({ domain, value, style }: Props) {
  if (value === null || value === undefined || value === '') return <span style={{ color: 'var(--fg-subtle)' }}>-</span>
  const meta = STATUS[domain][String(value)]
  return <span style={style}><Badge tone={meta?.color ?? 'neutral'}>{meta?.label ?? String(value)}</Badge></span>
}
