import { useEffect, useRef, useState, type ReactNode } from 'react'

// 行内二次确认：替代 antd Popconfirm。第一次点击变成「确认?」，3 秒内不再点就自动复原，
// 避免误删，也不弹浮层打断视线。
interface Props {
  message: string
  onConfirm: () => void
  children: ReactNode
  confirmLabel?: string
}

export default function InlineConfirm({ message, onConfirm, children, confirmLabel = '确认' }: Props) {
  const [armed, setArmed] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const arm = () => {
    setArmed(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setArmed(false), 3000)
  }

  if (!armed) {
    return (
      <span onClick={(e) => { e.stopPropagation(); arm() }} role="button" tabIndex={0} onKeyDown={(e) => { if (e.key === 'Enter') arm() }}>
        {children}
      </span>
    )
  }

  return (
    <span className="inline-flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
      <span className="text-[12px]" style={{ color: '#B91C1C' }} title={message}>{confirmLabel}?</span>
      <button
        type="button"
        className="text-[12px] px-1.5 py-0.5 rounded"
        style={{ background: '#DC2626', color: '#fff' }}
        onClick={() => { setArmed(false); onConfirm() }}
      >
        确定
      </button>
      <button
        type="button"
        className="text-[12px] px-1.5 py-0.5 rounded"
        style={{ color: 'var(--fg-muted)' }}
        onClick={() => setArmed(false)}
      >
        取消
      </button>
    </span>
  )
}
