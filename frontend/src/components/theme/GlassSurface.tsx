import LiquidGlass from 'liquid-glass-react'
import type { CSSProperties } from 'react'

// 液态玻璃底衬（liquid-glass-react）。
//
// 只画玻璃本身，不接管内容：绝对定位铺在容器底下，内容留在调用方的正常文档流里（需 relative）。
// 这样「开玻璃 / 关玻璃」两种模式的布局完全一致——之前把内容塞进绝对定位层，
// 关掉玻璃后内容回到流里，位置就和开启时对不上了。
//
// 玻璃只能做底衬，还因为它有 5 处内联样式/默认行为会打架：
//   translate(-50%,-50%) 居中、overflow:hidden 裁切浮层、box-shadow 大投影、
//   display:inline-flex 让内容层收缩、内容层高度不撑满。
// 这些在 theme.css 的 .lg-surface 里逐个覆盖；不接管内容就不用再和它们纠缠。
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
      className={`lg-surface ${className ?? ''}`}
      style={{
        position: 'absolute',
        // 必须是 50%：库内部用 translate(-50%,-50%) 居中，写 0px 会和那个位移叠加、偏出半个身位
        top: '50%',
        left: '50%',
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
