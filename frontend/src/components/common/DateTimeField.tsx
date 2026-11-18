import { CalendarDays } from 'lucide-react'
import dayjs from 'dayjs'
import { Calendar } from '@/components/shadcn/calendar'
import { Input } from '@/components/shadcn/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'

// 日期时间选择（"可以不设"的时间点，如 Key 的有效期）：Popover + Calendar + 时间输入。
// 值统一成带时区偏移的 ISO 8601 —— 服务端要求有效期必须带时区（否则 422），所以用 format() 而不是 toISOString()，
// 后者会转成 UTC，界面上选的本地下班时间会显示成另一天。
// null 表示"不设"（Key 的有效期不设 = 永不过期）。日历只禁掉今天之前，更细的过去时间由表单和服务端拦。
interface Props {
  id?: string
  value: string | null
  onChange: (value: string | null) => void
  /** 未设置时按钮上的文案，如「永不过期」 */
  placeholder: string
  /** 允许清空（清空 = null） */
  clearable?: boolean
  clearLabel?: string
  /** 时间输入框的无障碍名 */
  timeLabel?: string
}

export default function DateTimeField({ id, value, onChange, placeholder, clearable = true, clearLabel = '清除', timeLabel = '时间' }: Props) {
  const at = value ? dayjs(value) : null
  // 未设置时默认落在 23:59：这类"有效期至"的语义是当天结束前有效。
  // 用 00:00 会让"选今天"立刻变成过去时间（服务端 422、表单也报错），用户每次都得手动改时间。
  const hour = at?.hour() ?? 23
  const minute = at?.minute() ?? 59

  const pickDay = (d: Date | undefined) => {
    if (!d) return
    onChange(dayjs(d).hour(hour).minute(minute).second(0).format())
  }
  const pickTime = (text: string) => {
    const [h, m] = text.split(':').map(Number)
    onChange(dayjs(at ?? undefined).hour(h || 0).minute(m || 0).second(0).format())
  }

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          className="flex h-9 w-full max-w-[320px] items-center gap-1.5 rounded-lg border border-input bg-transparent px-3 text-left text-[13px] text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
        >
          <CalendarDays className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span className="truncate">{at ? at.format('YYYY-MM-DD HH:mm') : placeholder}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-0">
        <Calendar
          mode="single"
          selected={at?.toDate()}
          disabled={{ before: dayjs().startOf('day').toDate() }}
          onSelect={pickDay}
        />
        <div className="flex items-center gap-2 border-t border-border p-2">
          <Input
            type="time"
            aria-label={timeLabel}
            className="h-8 w-[110px] text-[12.5px]"
            value={at ? at.format('HH:mm') : '23:59'}
            onChange={(e) => pickTime(e.target.value)}
          />
          {clearable && value && (
            <button type="button" className="text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => onChange(null)}>{clearLabel}</button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}
