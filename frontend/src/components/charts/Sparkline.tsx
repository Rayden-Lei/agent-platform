import { Suspense } from 'react'
import { LazyTinyLine } from './lazy'

// 迷你折线：统计卡里的近 7 天走势，无坐标轴。
interface Props {
  data: number[]
  color?: string
  height?: number
}

export default function Sparkline({ data, color = '#1e40af', height = 36 }: Props) {
  if (!data.length) return null
  return (
    <Suspense fallback={<div style={{ height }} />}>
      <LazyTinyLine data={data} height={height} autoFit style={{ stroke: color, lineWidth: 1.5 }} animate={false} />
    </Suspense>
  )
}
