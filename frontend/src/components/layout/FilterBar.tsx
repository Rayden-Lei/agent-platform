import type { ReactNode } from 'react'
import { Download, RotateCw } from 'lucide-react'
import Button from '../ui/Button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

// 筛选条：wrap 布局放各筛选控件，右侧固定"重置 / 刷新 / 导出"。
interface Props {
  children: ReactNode
  onReset?: () => void
  onRefresh?: () => void
  onExport?: () => void
  loading?: boolean
  extra?: ReactNode
}

export default function FilterBar({ children, onReset, onRefresh, onExport, loading, extra }: Props) {
  return (
    <div className="filter-bar">
      <div className="flex flex-wrap items-center gap-2">{children}</div>
      <div className="flex items-center gap-1">
        {extra}
        {onReset && <Button variant="ghost" size="sm" onClick={onReset}>重置</Button>}
        {onRefresh && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" aria-label="刷新" disabled={loading} onClick={onRefresh}>
                <RotateCw className={loading ? 'size-3.5 animate-spin' : 'size-3.5'} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>刷新</TooltipContent>
          </Tooltip>
        )}
        {onExport && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="sm" aria-label="导出当前页 CSV" onClick={onExport}>
                <Download className="size-3.5" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>导出当前页 CSV</TooltipContent>
          </Tooltip>
        )}
      </div>
    </div>
  )
}
