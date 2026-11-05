import { useState, type ReactNode } from 'react'
import { ChevronDown, Download, RotateCw, SlidersHorizontal } from 'lucide-react'
import Button from '../ui/Button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

// 筛选条：wrap 布局放各筛选控件，右侧固定「重置 / 刷新 / 导出」。
//
// 移动端（2026-11-06 改）：控件多时这一条会吃掉 116～156px，等于五分之一屏（审计日志实测 156px），
// 而列表本身才是要看的东西。窄屏改为可折叠：默认收起，只留一行「筛选」按钮与右侧操作；
// 带筛选条件时自动展开并标出条数，否则使用者会以为筛选丢了。
interface Props {
  children: ReactNode
  onReset?: () => void
  onRefresh?: () => void
  onExport?: () => void
  loading?: boolean
  extra?: ReactNode
  /** 当前生效的筛选条件数：>0 时窄屏自动展开并显示条数 */
  activeCount?: number
}

export default function FilterBar({ children, onReset, onRefresh, onExport, loading, extra, activeCount = 0 }: Props) {
  // null 表示「跟随筛选条件自动决定」；用户手动点过之后按他的选择来
  const [manual, setManual] = useState<boolean | null>(null)
  const expanded = manual ?? activeCount > 0
  return (
    <div className="filter-bar">
      {/* 窄屏的折叠开关：宽屏不显示（控件本来就一行放得下） */}
      <button
        type="button"
        onClick={() => setManual(!expanded)}
        aria-expanded={expanded}
        className="filter-bar-toggle"
      >
        <SlidersHorizontal className="size-3.5" />
        筛选
        {activeCount > 0 && (
          <span className="rounded-full px-1.5 text-[11px] leading-[16px]" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
            {activeCount}
          </span>
        )}
        <ChevronDown className="size-3.5" style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
      </button>
      <div className={expanded ? 'filter-bar-fields' : 'filter-bar-fields filter-bar-fields-collapsed'}>
        {children}
      </div>
      {/* 右侧操作组：窄屏上不能是 nowrap —— 里面除按钮还可能有页面塞进来的标签（定时任务页的
          「每 N 秒刷新」角标），一条不换行就会把整行顶出屏幕（320px 屏实测 385px） */}
      <div className="flex flex-wrap items-center justify-end gap-1">
        {extra}
        {onReset && <Button variant="ghost" size="md" onClick={onReset}>重置</Button>}
        {onRefresh && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="md" aria-label="刷新" disabled={loading} onClick={onRefresh}>
                <RotateCw className={loading ? 'size-3.5 animate-spin' : 'size-3.5'} />
              </Button>
            </TooltipTrigger>
            <TooltipContent>刷新</TooltipContent>
          </Tooltip>
        )}
        {onExport && (
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="md" aria-label="导出当前页 CSV" onClick={onExport}>
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
