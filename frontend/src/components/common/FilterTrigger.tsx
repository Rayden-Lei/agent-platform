import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from 'cn'

// 筛选条里的自绘触发器（可搜索下拉、时间范围）：视觉与 shadcn 的 SelectTrigger 完全一致。
// 不共用会导致同一行里一半是 shadcn Select（透明底、10px 圆角、带 shadow-xs），
// 一半是 Button（填充底、12px 圆角、无投影），高度虽然都是 32px，看起来却是两种控件。
export const FILTER_TRIGGER =
  'flex h-8 w-fit items-center justify-between gap-2 rounded-md border border-input bg-transparent px-3 text-[13px] whitespace-nowrap text-foreground shadow-xs transition-[color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*=size-])]:size-4 [&_svg:not([class*=text-])]:text-muted-foreground'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: ReactNode
  suffix?: ReactNode
  muted?: boolean
}

// 必须 forwardRef：PopoverTrigger 的 asChild 会往它身上挂锚点 ref。
const FilterTrigger = forwardRef<HTMLButtonElement, Props>(function FilterTrigger(
  { icon, suffix, muted, children, className, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type="button"
      className={cn(FILTER_TRIGGER, muted && 'text-muted-foreground', className)}
      {...rest}
    >
      <span className="flex min-w-0 items-center gap-1.5">
        {icon}
        <span className="truncate">{children}</span>
      </span>
      {suffix}
    </button>
  )
})

export default FilterTrigger
