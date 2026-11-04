import { useState } from 'react'
import { toast } from 'sonner'
import { errorText } from '../../utils/errors'

// 列内启停开关：乐观更新，失败回滚并提示；请求中禁用防连点。
// 迁移期改为自绘开关（原实现用 antd Switch），props 保持兼容。
interface Props {
  checked: boolean
  onToggle: () => Promise<unknown>
  disabled?: boolean
  size?: 'small' | 'default'
}

export default function EnableSwitch({ checked, onToggle, disabled, size = 'small' }: Props) {
  const [pending, setPending] = useState(false)
  const [optimistic, setOptimistic] = useState<boolean | null>(null)
  const value = optimistic ?? checked
  const w = size === 'small' ? 32 : 40
  const h = size === 'small' ? 18 : 22
  const knob = h - 4

  const change = async () => {
    if (pending || disabled) return
    setOptimistic(!checked)
    setPending(true)
    try {
      await onToggle()
    } catch (e) {
      toast.error(errorText(e, '操作失败'))
    } finally {
      setOptimistic(null)
      setPending(false)
    }
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={value ? '已启用，点击停用' : '已停用，点击启用'}
      disabled={disabled || pending}
      onClick={change}
      className="relative rounded-full transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0"
      style={{ width: w, height: h, background: value ? 'var(--accent)' : 'var(--border-strong)' }}
    >
      <span
        className="absolute rounded-full bg-white transition-transform"
        style={{
          width: knob,
          height: knob,
          top: 2,
          left: 2,
          transform: value ? `translateX(${w - knob - 4}px)` : 'none',
          opacity: pending ? 0.6 : 1,
        }}
      />
    </button>
  )
}
