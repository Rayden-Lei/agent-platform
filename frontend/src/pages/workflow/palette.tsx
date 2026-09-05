import type { ReactNode } from 'react'
import { PlayCircleOutlined, CheckCircleOutlined, RobotOutlined, ToolOutlined, BranchesOutlined, DatabaseOutlined, CodeOutlined, ApiOutlined, SyncOutlined, AuditOutlined, ForkOutlined, MergeCellsOutlined } from '@ant-design/icons'

// 工作流编辑器的节点库常量、节点摘要、画布 ↔ 后端 graph 的序列化。
// 画布数据与后端契约的映射：节点 {id, type, config, position}，连线 {from, to, when}。

export interface PaletteItem {
  type: string
  label: string
  color: string
  icon: ReactNode
  description: string
}

export const PALETTE: PaletteItem[] = [
  { type: 'start', label: '开始', color: '#15803d', icon: <PlayCircleOutlined />, description: '流程入口' },
  { type: 'end', label: '结束', color: '#b91c1c', icon: <CheckCircleOutlined />, description: '流程出口' },
  { type: 'agent', label: '智能体', color: '#1e40af', icon: <RobotOutlined />, description: '调用智能体' },
  { type: 'tool', label: '工具', color: '#0e7490', icon: <ToolOutlined />, description: '调用工具' },
  { type: 'condition', label: '条件', color: '#b45309', icon: <BranchesOutlined />, description: '条件分支' },
  { type: 'kb_retrieval', label: '知识库检索', color: '#0d9488', icon: <DatabaseOutlined />, description: '检索知识库' },
  { type: 'code', label: '代码执行', color: '#334155', icon: <CodeOutlined />, description: '执行 Python' },
  { type: 'http', label: 'HTTP请求', color: '#2563eb', icon: <ApiOutlined />, description: '调用接口' },
  { type: 'loop', label: '循环', color: '#0891b2', icon: <SyncOutlined />, description: '按次数/条件循环' },
  { type: 'human_review', label: '人工审核', color: '#d97706', icon: <AuditOutlined />, description: '暂停等待人工确认' },
  { type: 'parallel', label: '并行', color: '#7c3aed', icon: <ForkOutlined />, description: '扇出多条分支并发执行' },
  { type: 'join', label: '汇聚', color: '#6d28d9', icon: <MergeCellsOutlined />, description: '等待全部分支完成' },
]

export const paletteOf = (type: string) => PALETTE.find((p) => p.type === type)

// 支持 input_ref / output_field 通用配置的节点类型；join 只有 output_field，parallel / start / end 无配置
export const REF_CONFIGURABLE = ['agent', 'tool', 'kb_retrieval', 'code', 'http', 'human_review', 'loop', 'condition']

export interface NodeDegree { inbound: number; outbound: number }

// 生成节点摘要文案：根据节点类型与已保存的 config 提炼一行说明（如智能体名/URL/循环次数），
// 让画布上不开配置面板也能看出每个节点在干什么；并行 / 汇聚的摘要来自连线数量
export function buildDetail(nodeType: string, config: any, agents: any[], tools: any[], degree?: NodeDegree): string {
  if (nodeType === 'agent') { const a = agents.find((x: any) => x.id === config.agent_id); return a ? a.name : '未选择智能体' }
  if (nodeType === 'tool') return config.tool_name || '未选择工具'
  if (nodeType === 'condition') return config.expression || '未设表达式'
  if (nodeType === 'kb_retrieval') return config.kb_id ? '知识库检索' : '未选择知识库'
  if (nodeType === 'code') return '代码执行'
  if (nodeType === 'http') return config.url || '未配置URL'
  if (nodeType === 'loop') return config.expression ? '条件循环' : '循环 ' + (config.count || 1) + ' 次'
  if (nodeType === 'human_review') return config.instruction || '人工审核'
  if (nodeType === 'parallel') return (degree?.outbound || 0) + ' 条分支'
  if (nodeType === 'join') return (degree?.inbound || 0) + ' 条入边'
  return ''
}

export function degreeOf(nodeId: string, edges: any[]): NodeDegree {
  return { inbound: edges.filter((e) => e.target === nodeId).length, outbound: edges.filter((e) => e.source === nodeId).length }
}

// 把画布序列化成与保存 / 测试运行一致的 graph；边的 label 即后端的 when（并行出边没有 when）
export function toGraph(nodes: any[], edges: any[]) {
  return {
    nodes: nodes.map((n) => ({ id: n.id, type: n.data.nodeType, config: n.data.config, position: n.position })),
    edges: edges.map((e) => ({ from: e.source, to: e.target, when: e.label || undefined })),
  }
}

// 节点库列表：拖拽建节点，dragstart 时把节点类型写入 dataTransfer
export function PaletteList({ onDragStart }: { onDragStart: (event: any, type: string) => void }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: '#1f2937' }}>节点库</div>
      {PALETTE.map((p) => (
        <div key={p.type} draggable onDragStart={(e) => onDragStart(e, p.type)}
          style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', borderRadius: 8, border: '1px solid #e5e7eb', cursor: 'grab', background: '#fafafa', transition: 'all 0.15s' }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = p.color)} onMouseLeave={(e) => (e.currentTarget.style.borderColor = '#e5e7eb')}>
          <div style={{ width: 26, height: 26, borderRadius: 6, background: p.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 13, flexShrink: 0 }}>{p.icon}</div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 500, color: '#1f2937' }}>{p.label}</div>
            <div style={{ fontSize: 11, color: '#9ca3af' }}>{p.description}</div>
          </div>
        </div>
      ))}
      <div style={{ color: '#9ca3af', fontSize: 11, marginTop: 4, lineHeight: 1.5 }}>拖入画布编排；点击节点/连线配置。并行节点的出边不需要分支值。</div>
    </div>
  )
}
