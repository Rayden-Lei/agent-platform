import LiquidGlass from 'liquid-glass-react'
import type { CSSProperties, ReactNode } from 'react'

// 液态玻璃面板（liquid-glass-react）。
//
// 层次必须是：页面背景 → 玻璃（模糊 + 折射 + 淡色）→ 内容。内容要放在玻璃里面，
// 否则拿不到内层折射与高光；容器上也不能再压一层不透明底色，那会让 backdrop-filter
// 采样到白板，折射等于失效。
//
// 定位：库内部用 translate(-50%,-50%) 居中，所以 top/left 必须给 50% 并配 100% 尺寸，
// 写成 0px 会与那个位移叠加、把整层推出去半个身位（表现为糊成一片马赛克）。
// 绝对定位是为了不参与父级 flex 布局——库会额外渲染 3 个与内容并列的遮罩节点，
// 留在文档流里会多出几个 flex 子项把布局撑坏。
// behind：高度由内容决定的容器（如聊天输入框）用这个模式。内容进绝对定位层会让父级
// 失去流内高度、直接塌成 0，所以这时玻璃只做底衬，内容留在调用方的文档流里（需 relative）。
interface Props {
  children?: ReactNode
  enabled?: boolean
  behind?: boolean
  cornerRadius?: number
  className?: string
  style?: CSSProperties
}

export default function GlassSurface({ children, enabled = true, behind = false, cornerRadius = 0, className, style }: Props) {
  if (!enabled) {
    return behind ? null : <div className={className} style={style}>{children}</div>
  }
  return (
    <LiquidGlass
      cornerRadius={cornerRadius}
      elasticity={0}
      padding="0px"
      className={`lg-surface ${className ?? ''}`}
      style={{
        position: 'absolute',
        top: '50%',
        left: '50%',
        width: '100%',
        height: '100%',
        ...(behind ? { pointerEvents: 'none' as const } : null),
        ...style,
      }}
    >
      {behind ? null : children}
    </LiquidGlass>
  )
}
