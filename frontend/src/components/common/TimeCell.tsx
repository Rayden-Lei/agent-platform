import { formatDateTime, fromNow } from '../../utils/time'

// 时间单元格：列表默认绝对时间；工作台 / 会话列表用相对时间，绝对时间放 title 里（原生 tooltip，不引浮层）。
interface Props {
  value?: string | null
  mode?: 'absolute' | 'relative'
}

export default function TimeCell({ value, mode = 'absolute' }: Props) {
  if (!value) return <span style={{ color: 'var(--fg-subtle)' }}>-</span>
  if (mode === 'absolute') return <span className="whitespace-nowrap">{formatDateTime(value)}</span>
  return <span className="whitespace-nowrap" title={formatDateTime(value)}>{fromNow(value)}</span>
}
