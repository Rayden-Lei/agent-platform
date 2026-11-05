import { Handle, Position } from '@xyflow/react'

// 自定义节点渲染：左侧类型色图标 + 标签/摘要，左右各一个连接点（Handle）。
// 2026-11-05 改版：图标不再铺实色圆角块（画布上一排彩色方块很吵），改成细线图标 + 类型色；
// 节点更紧凑（横向 padding 10、纵向 8），一屏能多放两行。选中加粗边框 + 阴影，
// 配置有误（data.configError）时红框并在摘要处写原因。
export function FlowNode({ data, selected }: any) {
  const border = data.configError ? '1.5px solid #dc2626' : selected ? '1.5px solid ' + data.color : '1px solid var(--border)'
  return (
    <div
      style={{
        background: 'var(--card)',
        border,
        borderRadius: 8,
        boxShadow: selected ? '0 4px 14px rgba(15,23,42,0.12)' : '0 1px 3px rgba(15,23,42,0.06)',
        minWidth: 132,
        cursor: 'pointer',
      }}
    >
      <div className="flex items-center gap-2 px-2.5 py-2">
        <span className="flex shrink-0 items-center justify-center [&>svg]:size-[15px]" style={{ color: data.color }}>{data.icon}</span>
        <div className="min-w-0">
          <div className="text-[12.5px] font-medium leading-tight" style={{ color: 'var(--fg)' }}>{data.label}</div>
          {(data.configError || data.detail) && (
            <div className="mt-0.5 truncate text-[11px]" style={{ color: data.configError ? '#dc2626' : 'var(--fg-subtle)', maxWidth: 130 }}>
              {data.configError || data.detail}
            </div>
          )}
        </div>
      </div>
      <Handle type="target" position={Position.Left} style={{ width: 8, height: 8, background: 'var(--card)', border: '1.5px solid ' + data.color }} />
      <Handle type="source" position={Position.Right} style={{ width: 8, height: 8, background: 'var(--card)', border: '1.5px solid ' + data.color }} />
    </div>
  )
}

export const nodeTypes = { flow: FlowNode }
