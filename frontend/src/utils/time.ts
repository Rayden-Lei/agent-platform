import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

// 时间工具：全站统一格式，取代散落的 new Date().toLocaleString()（格式随浏览器 locale 漂移）。
// 后端返回带时区的 ISO 串，这里转本地时间显示。
dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

export const formatDateTime = (value?: string | null, fallback = '-') => (value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : fallback)
export const formatDate = (value?: string | null, fallback = '-') => (value ? dayjs(value).format('YYYY-MM-DD') : fallback)
export const formatShortTime = (value?: string | null, fallback = '-') => (value ? dayjs(value).format('MM-DD HH:mm') : fallback)
export const fromNow = (value?: string | null, fallback = '-') => (value ? dayjs(value).fromNow() : fallback)

// 耗时：毫秒 → 人读的单位
export function formatDuration(ms?: number | null, fallback = '-'): string {
  if (ms === null || ms === undefined) return fallback
  if (ms < 1000) return `${ms} ms`
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`
  const minutes = Math.floor(ms / 60_000)
  const seconds = Math.round((ms % 60_000) / 1000)
  return `${minutes} 分 ${String(seconds).padStart(2, '0')} 秒`
}

// 时间范围（RangePicker 的输出）→ 后端 <列>_from / <列>_to 参数：带时区的 ISO 串，左闭右开
export interface TimeRange { from?: string; to?: string }
export function rangeToParams(prefix: string, range?: [string, string] | null): Record<string, string | undefined> {
  if (!range) return { [`${prefix}_from`]: undefined, [`${prefix}_to`]: undefined }
  return { [`${prefix}_from`]: dayjs(range[0]).toISOString(), [`${prefix}_to`]: dayjs(range[1]).toISOString() }
}

// 快捷区间：[起, 止) 均为本地时间；"最近 N 天"含今天
export const RANGE_PRESETS: { label: string; value: () => [dayjs.Dayjs, dayjs.Dayjs] }[] = [
  { label: '今天', value: () => [dayjs().startOf('day'), dayjs().add(1, 'day').startOf('day')] },
  { label: '昨天', value: () => [dayjs().subtract(1, 'day').startOf('day'), dayjs().startOf('day')] },
  { label: '近 7 天', value: () => [dayjs().subtract(6, 'day').startOf('day'), dayjs().add(1, 'day').startOf('day')] },
  { label: '近 30 天', value: () => [dayjs().subtract(29, 'day').startOf('day'), dayjs().add(1, 'day').startOf('day')] },
  { label: '近 90 天', value: () => [dayjs().subtract(89, 'day').startOf('day'), dayjs().add(1, 'day').startOf('day')] },
]

export { dayjs }
