import type { DragEvent, ReactNode } from 'react'
import type { Edge, Node } from '@xyflow/react'
import { CirclePlay, CircleStop, Bot, Wrench, GitBranch, BookOpen, Code, Globe, Repeat, UserCheck, Split, Merge } from 'lucide-react'
import type { NodeFormValues } from './NodeConfigForm'
import type { WorkflowGraph } from '../../api'

// 工作流编辑器的节点库常量、节点摘要、画布 ↔ 后端 graph 的序列化。
// 画布数据与后端契约的映射：节点 {id, type, config, position}，连线 {from, to, when}。

export interface PaletteItem {
  type: string
  label: string
  color: string
  icon: ReactNode
  description: string
}

// 画布节点的 data：节点库里的外观（label/color/icon/description）+ 业务节点类型 + 后端存的 config + 画布摘要。
// 表单校验不过时把原因与表单原文也挂在这里（画布上标红，保存与测试运行被拦下）。
export interface FlowNodeData extends Record<string, unknown> {
  nodeType: string
  config: Record<string, any>
  detail: string
  label?: string
  color?: string
  icon?: ReactNode
  description?: string
  configError?: string
  errorField?: string
  formDraft?: NodeFormValues
}

// ReactFlow 自定义节点：type 固定为 'flow'，与 FlowNode.tsx 注册的 nodeTypes 键一一对应。
// 画布状态、事件回调都按它取类型，避免把节点推成 never
export type FlowNodeType = Node<FlowNodeData, 'flow'>

// 画布连线：label 为条件/循环分支值（true/false、loop/exit），并行出边没有 label
export type FlowEdgeType = Edge

export const PALETTE: PaletteItem[] = [
  // 图标统一走 16px 线框（lucide 默认 stroke），与侧栏菜单同一套视觉；颜色只保留类型区分，
  // 不再给图标铺色块——色块会把"拖拽源"渲染得像画布上的节点本身
  { type: 'start', label: '开始', color: '#15803d', icon: <CirclePlay />, description: '流程入口' },
  { type: 'end', label: '结束', color: '#b91c1c', icon: <CircleStop />, description: '流程出口' },
  { type: 'agent', label: '智能体', color: '#1e40af', icon: <Bot />, description: '调用智能体' },
  { type: 'tool', label: '工具', color: '#0e7490', icon: <Wrench />, description: '调用工具' },
  { type: 'condition', label: '条件', color: '#b45309', icon: <GitBranch />, description: '条件分支' },
  { type: 'kb_retrieval', label: '知识库检索', color: '#0d9488', icon: <BookOpen />, description: '检索知识库' },
  { type: 'code', label: '代码执行', color: '#334155', icon: <Code />, description: '执行 Python' },
  { type: 'http', label: 'HTTP 请求', color: '#2563eb', icon: <Globe />, description: '调用接口' },
  { type: 'loop', label: '循环', color: '#0891b2', icon: <Repeat />, description: '按次数/条件循环' },
  { type: 'human_review', label: '人工审核', color: '#d97706', icon: <UserCheck />, description: '暂停等待人工确认' },
  { type: 'parallel', label: '并行', color: '#7c3aed', icon: <Split />, description: '扇出多条分支并发执行' },
  { type: 'join', label: '汇聚', color: '#6d28d9', icon: <Merge />, description: '等待全部分支完成' },
]

export const paletteOf = (type: string) => PALETTE.find((p) => p.type === type)

// 支持 input_ref / output_field 通用配置的节点类型；join 只有 output_field，parallel / start / end 无配置
export const REF_CONFIGURABLE = ['agent', 'tool', 'kb_retrieval', 'code', 'http', 'human_review', 'loop', 'condition']

export interface NodeDegree { inbound: number; outbound: number }

// 生成节点摘要文案：根据节点类型与已保存的 config 提炼一行说明（如智能体名/URL/循环次数），
// 让画布上不开配置面板也能看出每个节点在干什么；并行 / 汇聚的摘要来自连线数量
// tools 形参保留：调用方按同一签名传参（agent 摘要用 agents 查名，工具摘要直接读 config.tool_name）
export function buildDetail(nodeType: string, config: any, agents: any[], _tools: any[], degree?: NodeDegree): string {
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

export function degreeOf(nodeId: string, edges: FlowEdgeType[]): NodeDegree {
  return { inbound: edges.filter((e) => e.target === nodeId).length, outbound: edges.filter((e) => e.source === nodeId).length }
}

// 把画布序列化成与保存 / 测试运行一致的 graph；边的 label 即后端的 when（并行出边没有 when）
export function toGraph(nodes: FlowNodeType[], edges: FlowEdgeType[]): WorkflowGraph {
  return {
    nodes: nodes.map((n) => ({ id: n.id, type: n.data.nodeType, config: n.data.config, position: n.position })),
    edges: edges.map((e) => ({ from: e.source, to: e.target, when: typeof e.label === 'string' ? e.label || undefined : undefined })),
  }
}

// 节点库列表：一行一个、扁平排列（2026-11-05 改版）。
// 之前是"彩色大方块 + 主标题 + 灰色副标题"的两行卡片，12 个节点在 320px 宽的栏里要滚一屏半，
// 而这里只是拖拽源，信息密度比留白重要。现在高度 30px、单行、图标用细线条不着底块，
// 副标题（流程入口 / 调用工具）只在悬停时以 title 提示给出。
// 拖拽建节点（dragstart 时把类型写入 dataTransfer），也可以点击添加到画布中央 ——
// 触屏上拖不了，移动端只能靠点击（docs/15 WF-01）
export function PaletteList({ onDragStart, onAdd }: { onDragStart: (event: DragEvent<HTMLDivElement>, type: string) => void; onAdd: (type: string) => void }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="px-2 pb-1.5 text-[11px] font-medium" style={{ color: 'var(--fg-subtle)' }}>节点库</div>
      {PALETTE.map((p) => (
        <div
          key={p.type}
          draggable
          onDragStart={(e) => onDragStart(e, p.type)}
          onClick={() => onAdd(p.type)}
          role="button"
          tabIndex={0}
          title={p.description}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onAdd(p.type) } }}
          className="flex cursor-grab items-center gap-2 rounded-md px-2 py-[5px] text-[12.5px] transition-colors hover:bg-accent active:cursor-grabbing"
          style={{ color: 'var(--fg-muted)' }}
        >
          <span className="flex size-[15px] shrink-0 items-center justify-center [&>svg]:size-[14px]" style={{ color: p.color }}>{p.icon}</span>
          <span className="truncate">{p.label}</span>
        </div>
      ))}
      <div className="mt-2 px-2 text-[11px] leading-snug" style={{ color: 'var(--fg-subtle)' }}>拖入或点击添加</div>
    </div>
  )
}
