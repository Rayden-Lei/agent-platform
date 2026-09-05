import { LazyLine } from './lazy'
import { PALETTE, statusSeriesColor } from './theme'

// 折线趋势：单序列或多序列（series 字段分色）；状态序列用固定语义色。
export interface TrendPoint { date: string; value: number; series?: string }
interface Props {
  data: TrendPoint[]
  height?: number
  yFormatter?: (v: number) => string
  area?: boolean
  statusSeries?: boolean
}

export default function TrendLine({ data, height, yFormatter, area = false, statusSeries = false }: Props) {
  const multi = data.some((d) => d.series !== undefined)
  const seriesNames = Array.from(new Set(data.map((d) => d.series).filter(Boolean))) as string[]
  const range = statusSeries ? seriesNames.map((s, i) => statusSeriesColor(s, PALETTE[i % PALETTE.length])) : PALETTE
  return (
    <LazyLine
      data={data}
      xField="date"
      yField="value"
      colorField={multi ? 'series' : undefined}
      height={height}
      autoFit
      style={{ lineWidth: 2 }}
      area={area ? { style: { fillOpacity: 0.12 } } : undefined}
      scale={{ color: { range } }}
      axis={{ y: { labelFormatter: yFormatter ? (v: number) => yFormatter(v) : undefined }, x: { labelAutoHide: true } }}
      legend={multi ? { color: { position: 'top' } } : false}
      animate={false}
    />
  )
}
