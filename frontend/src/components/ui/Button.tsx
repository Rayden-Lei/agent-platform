import type { ButtonHTMLAttributes, ReactNode } from 'react'

// 按钮：迁移期替代 antd Button。视觉走新 token，尺寸与语义对齐原来那套（primary / default / text / danger）。
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

interface Props extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'className'> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
  block?: boolean
}

const SIZES: Record<Size, string> = {
  sm: 'h-7 px-2.5 text-[12.5px] gap-1',
  md: 'h-9 px-3.5 text-[13px] gap-1.5',
}

export default function Button({ variant = 'secondary', size = 'sm', icon, block, children, style, disabled, ...rest }: Props) {
  const base = 'inline-flex items-center justify-center rounded-lg font-medium transition-colors whitespace-nowrap disabled:opacity-45 disabled:cursor-not-allowed'
  const look: Record<Variant, React.CSSProperties> = {
    primary: { background: 'var(--accent)', color: 'var(--accent-fg)', border: '1px solid var(--accent)' },
    secondary: { background: 'var(--bg-elev)', color: 'var(--fg)', border: '1px solid var(--border-strong)' },
    ghost: { background: 'transparent', color: 'var(--fg-muted)', border: '1px solid transparent' },
    danger: { background: 'transparent', color: '#DC2626', border: '1px solid rgba(220,38,38,.35)' },
  }
  return (
    <button
      type="button"
      disabled={disabled}
      className={`${base} ${SIZES[size]} ${block ? 'w-full' : ''}`}
      style={{ ...look[variant], ...style }}
      {...rest}
    >
      {icon && <span className="flex items-center text-[13px]">{icon}</span>}
      {children}
    </button>
  )
}
