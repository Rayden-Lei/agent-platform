import { LazyLine } from './lazy'
import { AREA_FILL_OPACITY, AXIS_STYLE, LINE_STYLE, PALETTE, statusSeriesColor } from './theme'

// 折线趋势：单序列或多序列（series 字段分色）；状态序列用固定语义色。
// 样式走 theme.ts 的统一配置（细线、浅网格、无边框轴）。
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
      style={LINE_STYLE}
      area={area ? { style: { fillOpacity: AREA_FILL_OPACITY } } : undefined}
      scale={{ color: { range } }}
      axis={{ x: AXIS_STYLE.x, y: { ...AXIS_STYLE.y, labelFormatter: yFormatter ? (v: number) => yFormatter(v) : undefined } }}
      legend={multi ? { color: { position: 'top' } } : false}
      animate={false}
    />
  )
}