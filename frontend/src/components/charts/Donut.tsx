import { LazyPie } from './lazy'
import { PALETTE, STATUS_COLORS } from './theme'

// 环图：占比分布（运行状态、文档状态）；statusColors 时按状态语义色。
export interface DonutSlice { type: string; value: number; key?: string }
interface Props {
  data: DonutSlice[]
  height?: number
  statusColors?: boolean
}

export default function Donut({ data, height, statusColors = false }: Props) {
  const range = statusColors ? data.map((d) => STATUS_COLORS[d.key ?? ''] ?? PALETTE[0]) : PALETTE
  return (
    <LazyPie
      data={data}
      angleField="value"
      colorField="type"
      innerRadius={0.62}
      height={height}
      autoFit
      scale={{ color: { range } }}
      label={{ text: 'value', position: 'outside' }}
      legend={{ color: { position: 'right' } }}
      animate={false}
    />
  )
}
