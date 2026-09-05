import { useMemo } from 'react'
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { listAgents, listTools, OPTIONS_PAGE, type WorkflowGraph } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import { buildDetail, degreeOf, paletteOf } from './palette'
import { nodeTypes } from './FlowNode'

// 只读的画布预览：与编辑器同一套节点外观与摘要，但不可拖拽 / 连线 / 选中；用于详情页概览。
interface Props { graph: WorkflowGraph; height?: number }

export default function GraphPreview({ graph, height = 360 }: Props) {
  // 摘要里的智能体 / 工具名依赖下拉数据，与编辑器一致取前 100 条
  const refs = useAsyncData(async () => { const [a, t] = await Promise.all([listAgents(OPTIONS_PAGE), listTools(OPTIONS_PAGE)]); return { agents: a.items, tools: t.items } }, [])
  const edges = useMemo(() => (graph.edges || []).map((e, i) => ({ id: 'e' + i, source: e.from, target: e.to, label: e.when || undefined })), [graph])
  const nodes = useMemo(() => (graph.nodes || []).map((n) => ({
    id: n.id,
    type: 'flow',
    position: { x: n.position?.x ?? 80, y: n.position?.y ?? 80 },
    draggable: false,
    connectable: false,
    selectable: false,
    data: { ...paletteOf(n.type), nodeType: n.type, config: n.config || {}, detail: buildDetail(n.type, n.config || {}, refs.data?.agents ?? [], refs.data?.tools ?? [], degreeOf(n.id, edges)) },
  })), [graph, edges, refs.data])

  return (
    <div style={{ height, border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden', background: '#f8fafc' }}>
      <ReactFlowProvider>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} zoomOnScroll={false} preventScrolling={false}
          defaultEdgeOptions={{ style: { stroke: '#94a3b8', strokeWidth: 1.5 }, markerEnd: { type: 'arrowclosed', color: '#94a3b8' } }} proOptions={{ hideAttribution: true }}>
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="#dbe2ea" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  )
}
