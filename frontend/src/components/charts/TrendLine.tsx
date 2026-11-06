import { LazyLine } from './lazy'
import { AREA_FILL_OPACITY, AXIS_STYLE, LINE_STYLE, PALETTE, statusSeriesColor } from './theme'

// 折线趋势：单序列或多序列（series 字段分色）；状态序列用固定语义色。
// 样式走 theme.ts 的统一配置（细线、浅网格、无边框轴）。
//
// 2026-11-06：加点标记（point）。7 天只有 7 个数据点，铺在大宽度里没有标记时
// 就是一条飘着的细线，看不出哪天是哪天；有了圆点才能定位到具体日期。
export interface TrendPoint { date: string; value: number; series?: string }
interface Props {
  data: TrendPoint[]
  height?: number
  yFormatter?: (v: number) => string
  area?: boolean
  statusSeries?: boolean
  /** 是否显示数据点标记（点多时关掉，避免糊成一团） */
  point?: boolean
}

export default function TrendLine({ data, height, yFormatter, area = false, statusSeries = false, point }: Props) {
  const multi = data.some((d) => d.series !== undefined)
  const seriesNames = Array.from(new Set(data.map((d) => d.series).filter(Boolean))) as string[]
  const range = statusSeries ? seriesNames.map((s, i) => statusSeriesColor(s, PALETTE[i % PALETTE.length])) : PALETTE
  // 数据点少于 20 个时默认显示标记：点少时标记帮助定位，点多时会糊
  const showPoint = point ?? data.length <= 20
  return (
    <LazyLine
      data={data}
      xField="date"
      yField="value"
      colorField={multi ? 'series' : undefined}
      height={height}
      autoFit
      style={LINE_STYLE}
      point={showPoint ? { size: 3, shape: 'circle', style: { lineWidth: 1.5, stroke: '#fff' } } : false}
      area={area ? { style: { fillOpacity: AREA_FILL_OPACITY } } : undefined}
      scale={{ color: { range } }}
      axis={{ x: { ...AXIS_STYLE.x, labelAutoRotate: false }, y: { ...AXIS_STYLE.y, labelFormatter: yFormatter ? (v: number) => yFormatter(v) : undefined } }}
      legend={multi ? { color: { position: 'top' } } : false}
      animate={false}
    />
  )
}
