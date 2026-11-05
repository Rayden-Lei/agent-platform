import { useState } from 'react'
import { CalendarIcon } from 'lucide-react'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Calendar } from '@/components/shadcn/calendar'
import FilterTrigger from './FilterTrigger'
import { dayjs } from '../../utils/time'

// 时间区间筛选：带"今天 / 近 7 天 …"快捷项，输出 ISO 串对（左闭右开，由 rangeToParams 转成后端参数）。
interface Props {
  value?: [string, string] | null
  onChange: (value?: [string, string]) => void
  showTime?: boolean
  style?: React.CSSProperties
}

// 快捷项在本地算，避免引入 antd 的 presets
const PRESETS: { label: string; range: () => [Date, Date] }[] = [
  { label: '今天', range: () => [dayjs().startOf('day').toDate(), dayjs().add(1, 'day').startOf('day').toDate()] },
  { label: '昨天', range: () => [dayjs().subtract(1, 'day').startOf('day').toDate(), dayjs().startOf('day').toDate()] },
  { label: '近 7 天', range: () => [dayjs().subtract(6, 'day').startOf('day').toDate(), dayjs().add(1, 'day').startOf('day').toDate()] },
  { label: '近 30 天', range: () => [dayjs().subtract(29, 'day').startOf('day').toDate(), dayjs().add(1, 'day').startOf('day').toDate()] },
  { label: '近 90 天', range: () => [dayjs().subtract(89, 'day').startOf('day').toDate(), dayjs().add(1, 'day').startOf('day').toDate()] },
]

export default function DateRangeFilter({ value, onChange, style }: Props) {
  const [open, setOpen] = useState(false)
  const from = value?.[0] ? dayjs(value[0]) : null
  const to = value?.[1] ? dayjs(value[1]) : null
  const label = from && to ? `${from.format('MM-DD HH:mm')} ~ ${to.format('MM-DD HH:mm')}` : '时间范围'

  const pick = (range?: [Date, Date]) => {
    if (!range) { onChange(undefined); return }
    onChange([range[0].toISOString(), range[1].toISOString()])
    setOpen(false)
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <FilterTrigger icon={<CalendarIcon className="size-3.5" />} muted={!value} style={style} aria-label="时间范围">
          {label}
        </FilterTrigger>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-0">
        <div className="flex">
          <div className="flex w-[112px] flex-col gap-0.5 border-r border-border p-2">
            {PRESETS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => pick(p.range())}
                className="rounded-md px-2 py-1.5 text-left text-[12.5px] text-muted-foreground hover:bg-accent hover:text-foreground"
              >
                {p.label}
              </button>
            ))}
            {value && (
              <button
                type="button"
                onClick={() => { onChange(undefined); setOpen(false) }}
                className="rounded-md px-2 py-1.5 text-left text-[12.5px] text-destructive hover:bg-destructive/10"
              >
                清除
              </button>
            )}
          </div>
          <Calendar
            mode="range"
            selected={{ from: from?.toDate(), to: to?.toDate() }}
            onSelect={(range) => {
              if (range?.from && range?.to) pick([range.from, range.to])
              else if (range?.from) pick([range.from, dayjs(range.from).endOf('day').toDate()])
            }}
            numberOfMonths={2}
          />
        </div>
      </PopoverContent>
    </Popover>
  )
}
