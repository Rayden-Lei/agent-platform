import type { ReactNode } from 'react'
import { cn } from 'cn'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/shadcn/sheet'

// 抽屉：shadcn Sheet 的项目封装。整高、右侧滑出，正文滚动，标题与按钮栏固定。
// 长表单（模板、智能体装配、密钥、定时任务、用户、模型、工具）与详情查看都走这里，不用弹窗。
interface Props {
  open: boolean
  title?: ReactNode
  description?: ReactNode
  onClose: () => void
  footer?: ReactNode
  /** 头部右侧的额外按钮（例如"编辑"） */
  extra?: ReactNode
  width?: number
  children: ReactNode
  bodyClassName?: string
  /** 表单级错误：显示在**按钮栏正上方**（固定区，不随正文滚动）。
   *
   *  表单里自己渲染错误时，它落在正文末尾 —— 正文比一屏长时（技能、MCP、智能体装配都是），
   *  点保存 → 409 重名 → 错误文案在屏幕外，用户看到的是"按钮闪了一下没反应"。
   *  提到这里之后，无论正文滚到哪里，报错都在点保存的那只眼睛旁边。 */
  error?: string | null
}

export default function Drawer({ open, title, description, onClose, footer, extra, width = 760, children, bodyClassName, error }: Props) {
  return (
    <Sheet open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0"
        style={{ maxWidth: width }}
      >
        <SheetHeader className="shrink-0 border-b border-border px-5 py-3.5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <SheetTitle className="text-[15px]">{title}</SheetTitle>
              {description && <SheetDescription className="text-[12.5px]">{description}</SheetDescription>}
            </div>
            {extra && <div className="flex shrink-0 items-center gap-2 pr-6">{extra}</div>}
          </div>
        </SheetHeader>

        <div className={cn('min-h-0 flex-1 overflow-y-auto px-5 py-4', bodyClassName)}>
          {children}
        </div>

        {error && (
          <div className="shrink-0 border-t border-border bg-[var(--danger-bg,rgba(220,38,38,0.06))] px-5 py-2">
            <p className="m-0 whitespace-pre-wrap break-words text-[12.5px] text-destructive">{error}</p>
          </div>
        )}
        {footer && <div className="shrink-0 border-t border-border px-5 py-3 flex justify-end gap-2">{footer}</div>}
      </SheetContent>
    </Sheet>
  )
}
