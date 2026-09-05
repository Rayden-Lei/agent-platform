import { Tooltip } from 'antd'
import { formatDateTime, fromNow } from '../../utils/time'

// 时间单元格：列表默认绝对时间；工作台 / 会话列表用相对时间并在 Tooltip 里给绝对时间。
interface Props {
  value?: string | null
  mode?: 'absolute' | 'relative'
}

export default function TimeCell({ value, mode = 'absolute' }: Props) {
  if (!value) return <span style={{ color: '#9ca3af' }}>-</span>
  if (mode === 'absolute') return <span style={{ whiteSpace: 'nowrap' }}>{formatDateTime(value)}</span>
  return <Tooltip title={formatDateTime(value)}><span style={{ whiteSpace: 'nowrap' }}>{fromNow(value)}</span></Tooltip>
}
