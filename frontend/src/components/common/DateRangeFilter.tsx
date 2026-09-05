import { DatePicker } from 'antd'
import { RANGE_PRESETS, dayjs } from '../../utils/time'

// 时间区间筛选：带"今天 / 近 7 天 …"快捷项，输出 ISO 串对（左闭右开，由 rangeToParams 转成后端参数）。
interface Props {
  value?: [string, string] | null
  onChange: (value?: [string, string]) => void
  showTime?: boolean
  style?: React.CSSProperties
}

export default function DateRangeFilter({ value, onChange, showTime = false, style }: Props) {
  return (
    <DatePicker.RangePicker
      value={value ? [dayjs(value[0]), dayjs(value[1])] : null}
      showTime={showTime}
      allowClear
      presets={RANGE_PRESETS.map((p) => ({ label: p.label, value: p.value() }))}
      onChange={(range) => onChange(range && range[0] && range[1] ? [range[0].toISOString(), range[1].toISOString()] : undefined)}
      style={{ width: showTime ? 380 : 260, ...style }}
    />
  )
}
