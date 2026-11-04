import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from 'cn'
import { Button as ShadcnButton } from '@/components/shadcn/button'

// 按钮：底层就是 shadcn 的 Button（焦点环、禁用态、asChild 都由它负责），
// 这里只保留项目原来的四个语义与两档尺寸，避免每迁一个页面就改一遍调用处。
// 必须 forwardRef：TooltipTrigger / PopoverTrigger 的 asChild 会给它挂 ref。
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  icon?: ReactNode
  block?: boolean
  className?: string
}

const SIZES: Record<Size, string> = {
  sm: 'h-7 px-2.5 text-[12.5px] gap-1 rounded-lg',
  md: 'h-8 px-3.5 text-[13.5px] gap-1.5 rounded-lg',
}

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-none',
  secondary: 'bg-card text-foreground border border-border-strong hover:bg-accent shadow-none',
  ghost: 'bg-transparent text-muted-foreground hover:bg-accent hover:text-foreground shadow-none',
  danger: 'bg-transparent text-destructive border border-destructive/35 hover:bg-destructive/10 shadow-none',
}

const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = 'secondary', size = 'sm', icon, block, children, disabled, className, ...rest },
  ref,
) {
  return (
    <ShadcnButton
      ref={ref}
      type="button"
      disabled={disabled}
      className={cn('font-medium', SIZES[size], VARIANTS[variant], block && 'w-full', className)}
      {...rest}
    >
      {icon && <span className="flex items-center text-[13px]">{icon}</span>}
      {children}
    </ShadcnButton>
  )
})

export default Button
