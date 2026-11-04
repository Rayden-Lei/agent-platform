import type { ReactNode } from 'react'
import { cn } from 'cn'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/shadcn/dialog'

// 弹窗：shadcn Dialog 的项目封装，解决"内容比视口高、底部按钮被切掉"的问题。
// 高度固定为视口内（max-h-[100dvh-3rem]），标题与按钮栏不滚，只有正文滚动。
// 选择形态的规矩（docs/07）：字段 ≤ 6 个、结构简单 → 弹窗；长表单 / 多段内容 → Drawer。
type Size = 'sm' | 'md' | 'lg' | 'xl' | 'full'

const WIDTH: Record<Size, string> = {
  sm: 'sm:max-w-[420px]',
  md: 'sm:max-w-[560px]',
  lg: 'sm:max-w-[760px]',
  xl: 'sm:max-w-[980px]',
  full: 'sm:max-w-[calc(100vw-3rem)]',
}

interface Props {
  open: boolean
  title?: ReactNode
  description?: ReactNode
  onClose: () => void
  footer?: ReactNode
  size?: Size
  children: ReactNode
  /** 正文区域的额外类名（例如表单间距） */
  bodyClassName?: string
}

export default function Modal({ open, title, description, onClose, footer, size = 'md', children, bodyClassName }: Props) {
  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent
        className={cn(
          'flex max-h-[calc(100dvh-3rem)] flex-col gap-0 p-0',
          WIDTH[size],
        )}
      >
        <DialogHeader className="shrink-0 border-b border-border px-5 py-3.5">
          <DialogTitle className="text-[15px]">{title}</DialogTitle>
          {description && <DialogDescription className="text-[12.5px]">{description}</DialogDescription>}
        </DialogHeader>

        <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-4', bodyClassName)}>
          {children}
        </div>

        {footer && <DialogFooter className="shrink-0 border-t border-border px-5 py-3">{footer}</DialogFooter>}
      </DialogContent>
    </Dialog>
  )
}
