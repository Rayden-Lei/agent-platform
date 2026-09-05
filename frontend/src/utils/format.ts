// 数字类展示的统一格式：token 用千分位，成本固定 4 位小数（元），百分比保留 1 位。

export const formatNumber = (value?: number | null, fallback = '-') => (value === null || value === undefined ? fallback : value.toLocaleString('zh-CN'))

// 大数缩写：12.3k / 4.5M，用在统计卡与图表轴
export function compactNumber(value?: number | null, fallback = '-'): string {
  if (value === null || value === undefined) return fallback
  const abs = Math.abs(value)
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`
  if (abs >= 1_000) return `${(value / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`
  return String(value)
}

export const formatCost = (value?: number | null, fallback = '-') => (value === null || value === undefined ? fallback : `¥${value.toFixed(4)}`)

export const formatPercent = (ratio?: number | null, fallback = '-') => (ratio === null || ratio === undefined ? fallback : `${(ratio * 100).toFixed(1)}%`)

// 环比：今日相对昨日的变化，null 表示无法比较（昨日为 0）
export function deltaRatio(current: number, previous: number): number | null {
  if (!previous) return null
  return (current - previous) / previous
}
