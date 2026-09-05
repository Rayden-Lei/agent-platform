import { LazyColumn } from './lazy'
import { PALETTE, statusSeriesColor } from './theme'

// 柱状图：按 series 堆叠；horizontal 时是条形图（用于 Top N 排行）。
export interface BarPoint { x: string; value: number; series?: string }
interface Props {
  data: BarPoint[]
  height?: number
  horizontal?: boolean
  yFormatter?: (v: number) => string
  statusSeries?: boolean
}

export default function StackedBar({ data, height, horizontal = false, yFormatter, statusSeries = false }: Props) {
  const multi = data.some((d) => d.series !== undefined)
  const seriesNames = Array.from(new Set(data.map((d) => d.series).filter(Boolean))) as string[]
  const range = statusSeries ? seriesNames.map((s, i) => statusSeriesColor(s, PALETTE[i % PALETTE.length])) : PALETTE
  return (
    <LazyColumn
      data={data}
      xField="x"
      yField="value"
      colorField={multi ? 'series' : undefined}
      stack={multi}
      height={height}
      autoFit
      coordinate={horizontal ? { transform: [{ type: 'transpose' }] } : undefined}
      scale={{ color: { range } }}
      axis={{ y: { labelFormatter: yFormatter ? (v: number) => yFormatter(v) : undefined }, x: { labelAutoHide: true } }}
      legend={multi ? { color: { position: 'top' } } : false}
      animate={false}
    />
  )
}
