import { LazyPie } from './lazy'
import { PALETTE, STATUS_COLORS } from './theme'

// 环图：占比分布（运行状态、文档状态）；statusColors 时按状态语义色。
// 2026-11-06 精致化：环加粗一点（innerRadius 0.62→0.58）、外标签只留数字（淡色小字，
// 不再拖着引导线戳出去）、图例右侧并带数量。
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
      innerRadius={0.58}
      height={height}
      autoFit
      scale={{ color: { range } }}
      label={{
        text: 'value',
        position: 'outside',
        fontSize: 11,
        fill: '#94a3b8',
        connectorStroke: '#e2e8f0',
        connectorLineWidth: 1,
      }}
      legend={{ color: { position: 'right', itemLabelFontSize: 12 } }}
      style={{ lineWidth: 2, stroke: '#fff' }}
      animate={false}
    />
  )
}