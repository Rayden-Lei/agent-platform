import { LazyColumn } from './lazy'
import { AXIS_STYLE, BAR_STYLE, PALETTE, statusSeriesColor } from './theme'

// 柱状图：按 series 堆叠；horizontal 时是条形图（用于 Top N 排行）。
// 样式走 theme.ts 的统一配置（圆角柱、浅网格、无边框轴）。
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
  // 圆角方向：竖柱圆顶部，横向条形图经 transpose 后圆在「值」那端（视觉上是右端）
  const radius = horizontal ? { radiusTop: 0, radiusBottom: 0, radiusRight: 3, radiusLeft: 0 } : BAR_STYLE
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
      axis={{ x: { ...AXIS_STYLE.x, labelFormatter: undefined }, y: { ...AXIS_STYLE.y, labelFormatter: yFormatter ? (v: number) => yFormatter(v) : undefined } }}
      legend={multi ? { color: { position: 'top' } } : false}
      style={{ ...radius, maxWidth: BAR_STYLE.maxWidth }}
      animate={false}
    />
  )
}