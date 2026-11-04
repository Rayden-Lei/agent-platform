import LiquidGlass from 'liquid-glass-react'
import type { CSSProperties } from 'react'

// 液态玻璃背景层（liquid-glass-react）。
//
// 为什么是「背景层」而不是「包住内容」：这个库返回的 Fragment 里有 3 个与内容并列的
// 遮罩节点，且默认 position:relative，直接包进 flex 容器会多出几个 flex 子项把布局撑坏。
// 所以这里只渲染玻璃本身，绝对定位铺在容器底下，内容仍走原来的文档流。
// 调用方需要给父级 position:relative。
//
// 另外三个默认值必须改掉，它们是为按钮/卡片设计的：cornerRadius 999 是胶囊形、
// elasticity 0.15 会让内容跟着鼠标动、padding 24px 32px 会挤走内容。
// 注意 top 要写字符串 '0px'：库内部是 `baseStyle.top || '50%'`，传数字 0 会被当假值。
interface Props {
  enabled?: boolean
  cornerRadius?: number
  className?: string
  style?: CSSProperties
}

export default function GlassSurface({ enabled = true, cornerRadius = 0, className, style }: Props) {
  if (!enabled) return null
  return (
    <LiquidGlass
      cornerRadius={cornerRadius}
      elasticity={0}
      padding="0px"
      className={`[&>.glass]:h-full [&>.glass]:w-full ${className ?? ''}`}
      style={{
        position: 'absolute',
        top: '0px',
        left: '0px',
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        ...style,
      }}
    >
      {null}
    </LiquidGlass>
  )
}
