import { Handle, Position } from '@xyflow/react'

// 自定义节点渲染：左侧类型色块图标 + 标签/摘要，左右各一个连接点（Handle）；
// 选中时加粗边框并加阴影。所有节点类型共用这一种外观，靠 data.color 区分。配置有误（data.configError）时红框并在摘要处写原因。
export function FlowNode({ data, selected }: any) {
  const border = data.configError ? '2px solid #dc2626' : selected ? '2px solid ' + data.color : '1px solid #e5e7eb'
  return (
    <div style={{ background: '#fff', border, borderRadius: 10, boxShadow: selected ? '0 6px 20px rgba(15,23,42,0.16)' : '0 2px 6px rgba(15,23,42,0.06)', minWidth: 150, cursor: 'pointer', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px' }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, background: data.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, flexShrink: 0 }}>{data.icon}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#1f2937', lineHeight: 1.3 }}>{data.label}</div>
          {(data.configError || data.detail) && <div style={{ fontSize: 11, color: data.configError ? '#dc2626' : '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 140 }}>{data.configError || data.detail}</div>}
        </div>
      </div>
      <Handle type="target" position={Position.Left} style={{ width: 9, height: 9, background: '#fff', border: '2px solid ' + data.color }} />
      <Handle type="source" position={Position.Right} style={{ width: 9, height: 9, background: '#fff', border: '2px solid ' + data.color }} />
    </div>
  )
}

export const nodeTypes = { flow: FlowNode }
