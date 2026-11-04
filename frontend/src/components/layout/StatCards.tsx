import type { ReactNode } from 'react'
import { ArrowDown, ArrowUp } from 'lucide-react'
import { Skeleton } from '@/components/shadcn/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { formatPercent } from '../../utils/format'

// 统计卡行：点击卡片可当筛选（active 高亮），可选环比与说明。加载中显示骨架，不显示 0。
export interface StatCardItem {
  key: string
  title: ReactNode
  value: ReactNode
  suffix?: ReactNode
  precision?: number
  color?: string
  icon?: ReactNode
  hint?: ReactNode
  delta?: number | null // 环比，null = 无法比较
  onClick?: () => void
  active?: boolean
}
interface Props {
  items: StatCardItem[]
  loading?: boolean
  cols?: 3 | 4 | 6 | 8
}

const GRID: Record<number, string> = {
  3: 'grid-cols-2 md:grid-cols-3',
  4: 'grid-cols-2 md:grid-cols-4',
  6: 'grid-cols-2 md:grid-cols-3 xl:grid-cols-6',
  8: 'grid-cols-2 md:grid-cols-4 xl:grid-cols-8',
}

export default function StatCards({ items, loading, cols = 4 }: Props) {
  return (
    <div className={`grid gap-3 ${GRID[cols] ?? GRID[4]}`}>
      {items.map((item) => {
        const body = (
          <div
            className={[
              'h-full rounded-xl border bg-card px-3.5 py-3 transition-colors',
              item.onClick ? 'cursor-pointer hover:border-border-strong' : '',
              item.active ? 'border-primary shadow-[0_0_0_2px_var(--accent-soft)]' : 'border-border',
            ].join(' ')}
            onClick={item.onClick}
          >
            {loading ? (
              <div className="flex flex-col gap-2">
                <Skeleton className="h-3 w-16" />
                <Skeleton className="h-6 w-24" />
              </div>
            ) : (
              <div className="flex items-center gap-3">
                {item.icon && (
                  <div className="stat-icon" style={{ background: item.color ?? 'var(--accent)' }}>{item.icon}</div>
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] text-muted-foreground">{item.title}</div>
                  <div className="flex items-baseline gap-1">
                    <span className="text-[22px] font-semibold leading-tight" style={{ color: item.color }}>
                      {item.value}
                    </span>
                    {item.suffix && <span className="text-[12.5px] text-muted-foreground">{item.suffix}</span>}
                  </div>
                  {item.delta !== undefined && (
                    <div className={`mt-0.5 flex items-center gap-1 text-[12px] ${item.delta === null ? 'text-muted-foreground' : item.delta >= 0 ? 'text-[#16a34a]' : 'text-destructive'}`}>
                      {item.delta === null ? '较昨日 -' : (
                        <>
                          {item.delta >= 0 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
                          较昨日 {formatPercent(Math.abs(item.delta))}
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )
        return item.hint ? (
          <Tooltip key={item.key}>
            <TooltipTrigger asChild><div>{body}</div></TooltipTrigger>
            <TooltipContent>{item.hint}</TooltipContent>
          </Tooltip>
        ) : <div key={item.key}>{body}</div>
      })}
    </div>
  )
}
