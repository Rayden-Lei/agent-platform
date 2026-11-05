import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls, MiniMap, addEdge, useNodesState, useEdgesState, useReactFlow } from '@xyflow/react'
import type { XYPosition } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { toast } from 'sonner'
import { ArrowLeft, Blocks, Save } from 'lucide-react'
import { useNavigate, useParams } from 'react-router-dom'
import { getWorkflow, updateWorkflow, createWorkflow, listAgents, listTools, listKBs, testRunWorkflow, OPTIONS_PAGE } from '../api'
import { PaletteList, buildDetail, degreeOf, paletteOf, toGraph } from './workflow/palette'
import { nodeTypes } from './workflow/FlowNode'
import { collectNodeConfig, configToFormValues, type NodeFormValues } from './workflow/NodeConfigForm'
import ConfigPanel from './workflow/ConfigPanel'
import { useUnsaved } from '../store/unsaved'
import { useGuardedNavigate } from '../hooks/useGuardedNavigate'
import { Input } from '@/components/shadcn/input'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/shadcn/sheet'
import Button from '../components/ui/Button'
import Modal from '../components/ui/Modal'
import ErrorState from '../components/common/ErrorState'
import { errorText } from '../utils/errors'

// 工作流画布编辑器（基于 @xyflow/react）：左侧节点库拖拽或点击建节点，中间画布连线编排，
// 右侧为节点/连线配置面板（改动即写回）；支持测试运行与保存（新建/更新）。
// 节点库常量与序列化在 ./workflow/palette，节点外观在 ./workflow/FlowNode，配置表单在 ./workflow/NodeConfigForm，右侧面板在 ./workflow/ConfigPanel。
function EditorInner() {
  const navigate = useNavigate()
  const { id } = useParams()
  // isNew：路由无 id 即为新建模式（保存走 create），有 id 为编辑模式（走 update）
  const isNew = !id
  const [name, setName] = useState('未命名工作流')
  const [description, setDescription] = useState('')
  // 未保存标记：把当前画布序列化后与最近一次加载 / 保存的基线比较，只有真正改了才置 dirty
  const setDirty = useUnsaved((s) => s.setDirty)
  const guardedNavigate = useGuardedNavigate()
  const baseline = useRef<string | null>(null)
  // ReactFlow 的节点/边状态：nodes 的 data 里挂 nodeType/config/detail 等业务数据
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  // 配置面板下拉的数据源（智能体/工具/知识库各取前 100 条）
  const [agents, setAgents] = useState<any[]>([])
  const [tools, setTools] = useState<any[]>([])
  const [kbs, setKBs] = useState<any[]>([])
  // 当前选中的节点/连线：两者互斥，决定右侧配置面板展示什么
  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [selectedEdge, setSelectedEdge] = useState<any>(null)
  // 节点配置表单的值（受控）：与选中节点一一对应
  const [nodeValues, setNodeValues] = useState<NodeFormValues>(() => configToFormValues({}))
  const [nodeErrorField, setNodeErrorField] = useState<string | null>(null)
  // 测试运行状态：按开始节点声明填的入参 / 结果 / 请求中标记（docs/15 WF-04：不再手写 JSON 字典）
  const [testInputs, setTestInputs] = useState<Record<string, unknown>>({})
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [edgeLabel, setEdgeLabel] = useState('')
  const [showPalette, setShowPalette] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  // 删除确认：待确认的元素，确认后真正删除
  const [pendingDelete, setPendingDelete] = useState<{ nodes: any[]; edges: any[] } | null>(null)
  const pendingResolve = useRef<((ok: boolean) => void) | null>(null)
  const canvasRef = useRef<HTMLDivElement>(null)
  const { screenToFlowPosition, deleteElements, fitView } = useReactFlow()
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.innerWidth < 768)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const onChange = () => setIsMobile(mq.matches)
    onChange()
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    // 并行加载配置面板下拉数据；编辑模式再拉取工作流详情
    Promise.all([listAgents(OPTIONS_PAGE), listTools(OPTIONS_PAGE), listKBs(OPTIONS_PAGE)])
      .then(([a, t, k]) => { setAgents(a.items); setTools(t.items); setKBs(k.items) })
      .catch((e: any) => toast.error(e.response?.data?.detail || '加载选项失败'))
    if (!isNew && id) {
      // 把后端存的工作流 graph 映射成 ReactFlow 结构：
      // 节点按 type 从 PALETTE 取外观（图标/颜色），config 挂在 data 上供配置面板回填
      getWorkflow(Number(id)).then((wf) => {
        setName(wf.name)
        setDescription(wf.description || '')
        const ns = (wf.graph?.nodes || []).map((n: any) => {
          // 摘要先留空，避免用空 agents/tools 误显示"未选择智能体/工具"；
          // 真正的摘要由下方 [agents, tools] 的 effect 在数据就绪后派生
          return { id: n.id, type: 'flow', position: { x: n.position?.x ?? 80, y: n.position?.y ?? 80 }, data: { ...paletteOf(n.type), nodeType: n.type, config: n.config || {}, detail: '' } }
        })
        // 边 label 对应后端连线的 when 字段（条件分支的值）
        const es = (wf.graph?.edges || []).map((e: any, i: number) => ({ id: 'e' + i, source: e.from, target: e.to, label: e.when || undefined }))
        setNodes(ns)
        setEdges(es)
        baseline.current = JSON.stringify({ name: wf.name, description: wf.description || '', graph: toGraph(ns, es) })
      }).catch((e) => { setLoadError(errorText(e, '加载工作流失败')) })
    } else {
      baseline.current = JSON.stringify({ name: '未命名工作流', description: '', graph: toGraph([], []) })
    }
  }, [id])

  // 名称 / 描述 / 画布任一变化与基线不同即视为未保存；离开编辑器时清掉标记。
  // 有节点表单校验不过时也算未保存：坏值没写进 config，但离开会丢掉用户正在改的原文
  useEffect(() => {
    if (baseline.current === null) return
    setDirty(JSON.stringify({ name, description, graph: toGraph(nodes, edges) }) !== baseline.current || nodes.some((n) => n.data.configError))
  }, [name, description, nodes, edges, setDirty])
  useEffect(() => () => setDirty(false), [setDirty])

  // 摘要里智能体/工具名依赖 agents/tools 下拉数据，而工作流详情与这些数据是并行异步加载的，
  // 不能在 getWorkflow 的 then 里重建（闭包拿到的还是空数组）。改为独立 effect：
  // 等 agents/tools 就绪后，用最新的 config 重新派生所有节点的 detail 行。
  useEffect(() => {
    if (!agents.length && !tools.length) return
    setNodes((prev) => prev.map((n) => ({ ...n, data: { ...n.data, detail: buildDetail(n.data.nodeType, n.data.config, agents, tools, degreeOf(n.id, edges)) } })))
  }, [agents, tools])

  // 并行 / 汇聚节点的摘要是连线数量，连线变化时单独刷新这两类节点，不动其他节点
  useEffect(() => {
    setNodes((prev) => prev.map((n) => (n.data.nodeType === 'parallel' || n.data.nodeType === 'join')
      ? { ...n, data: { ...n.data, detail: buildDetail(n.data.nodeType, n.data.config, agents, tools, degreeOf(n.id, edges)) } }
      : n))
  }, [edges])

  // 新建节点：拖放时用落点坐标；点击节点库条目不带坐标，放到当前视口中心
  // （触屏上拖不了，移动端只能点击，docs/15 WF-01）
  const viewportCenter = (): XYPosition => {
    const rect = canvasRef.current?.getBoundingClientRect()
    if (!rect) return { x: 80, y: 80 }
    const c = screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 })
    // 75 / 25 约是节点宽高的一半，让节点中心落在视口中心；连续点击时逐个错开，免得叠成一个看不出来
    const offset = (nodes.length % 5) * 24
    return { x: c.x - 75 + offset, y: c.y - 25 + offset }
  }
  const addNode = (type: string, position?: XYPosition) => {
    const palette = paletteOf(type)
    if (!palette) return
    const pos = position ?? viewportCenter()
    setNodes((nds) => nds.concat({ id: 'node_' + Date.now(), type: 'flow', position: pos, data: { ...palette, nodeType: type, config: {}, detail: '' } }))
  }
  // 拖拽建节点：dragstart 时把节点类型写入 dataTransfer，drop 时把鼠标坐标换算成画布坐标作为初始位置
  const onDragStart = (event: any, type: string) => { event.dataTransfer.setData('application/reactflow', type); event.dataTransfer.effectAllowed = 'move' }
  const onDrop = (event: any) => {
    event.preventDefault()
    addNode(event.dataTransfer.getData('application/reactflow'), screenToFlowPosition({ x: event.clientX, y: event.clientY }))
  }
  // 从节点拖线到另一节点：默认新建一条连线
  const onConnect = useCallback((conn: any) => setEdges((eds) => addEdge(conn, eds)), [setEdges])

  // 选中节点并回填表单值。上次改出错的节点回填出错时的原文，不拿旧 config 盖掉没改完的内容
  const selectNode = (node: any) => {
    setSelectedNode(node)
    setSelectedEdge(null)
    setNodeErrorField(node.data.errorField ?? null)
    setNodeValues(node.data.formDraft ?? configToFormValues(node.data.config))
  }
  const onNodeClick = (_: any, node: any) => selectNode(node)
  // 点击连线：编辑分支值（label）；点击空白处取消所有选中
  const onEdgeClick = (_: any, edge: any) => { setSelectedEdge(edge); setSelectedNode(null); setEdgeLabel(edge.label || '') }
  const onPaneClick = () => { setSelectedNode(null); setSelectedEdge(null) }

  // 节点配置随改随写回（此前要点"应用配置"，不点就悄悄丢，docs/15 2.3 第 19 条）。
  // 校验不过：字段标红，节点上记下错误与表单原文，config 保持上一次合法的值，保存与测试运行会被拦下
  const onNodeChange = (patch: Partial<NodeFormValues>) => {
    if (!selectedNode) return
    const next = { ...nodeValues, ...patch }
    setNodeValues(next)
    const nid = selectedNode.id
    const collected = collectNodeConfig(selectedNode.data.nodeType, next, selectedNode.data.nodeType === 'tool' ? selectedToolParams : undefined)
    if ('error' in collected) {
      setNodeErrorField(collected.field)
      setNodes((nds) => nds.map((n) => (n.id === nid ? { ...n, data: { ...n.data, configError: collected.error, errorField: collected.field, formDraft: next } } : n)))
      return
    }
    setNodeErrorField(null)
    const detail = buildDetail(selectedNode.data.nodeType, collected.config, agents, tools, degreeOf(nid, edges))
    setNodes((nds) => nds.map((n) => (n.id === nid ? { ...n, data: { ...n.data, config: collected.config, detail, configError: undefined, errorField: undefined, formDraft: undefined } } : n)))
  }

  // 分支值随输入写回连线 label（条件分支为 true/false，循环分支为 loop/exit）
  const changeEdgeLabel = (value: string) => {
    setEdgeLabel(value)
    if (selectedEdge) setEdges((eds) => eds.map((e) => (e.id === selectedEdge.id ? { ...e, label: value || undefined } : e)))
  }

  // 删除确认：React Flow 默认按 Backspace 删除选中元素，误按即删且没有撤销（撤销在 3B 的 WF-20）。
  // 按钮删除也走 deleteElements，同样先过这里；涉及节点才弹（连带删掉的连线一并列出），只删连线不弹，删了重连即可
  const confirmDelete = ({ nodes: ns, edges: es }: { nodes: any[]; edges: any[] }) => {
    if (!ns.length) return Promise.resolve(true)
    return new Promise<boolean>((resolve) => {
      pendingResolve.current = resolve
      setPendingDelete({ nodes: ns, edges: es })
    })
  }
  const settleDelete = (ok: boolean) => {
    pendingResolve.current?.(ok)
    pendingResolve.current = null
    setPendingDelete(null)
  }
  // 删除后清掉指向已删元素的选中，否则右侧面板还停在已删的节点上（Backspace 删除此前就有这个问题）
  const onDeleted = ({ nodes: ns, edges: es }: { nodes: any[]; edges: any[] }) => {
    if (selectedNode && ns.some((n) => n.id === selectedNode.id)) setSelectedNode(null)
    if (selectedEdge && es.some((e) => e.id === selectedEdge.id)) setSelectedEdge(null)
  }
  const deleteSelected = () => deleteElements({ nodes: selectedNode ? [{ id: selectedNode.id }] : [], edges: selectedEdge ? [{ id: selectedEdge.id }] : [] })

  // 有节点配置校验不过时拦下保存与测试运行：提示是哪个节点，选中它并移到视口里（AC-034 ③）
  const blockedByInvalidNode = () => {
    const bad: any = nodes.find((n) => n.data.configError)
    if (!bad) return false
    toast.error(`节点「${bad.data.label}${bad.data.detail ? ' · ' + bad.data.detail : ''}」配置有误：${bad.data.configError}`)
    // 已选中的不重选：重选会清掉当前的标红
    if (bad.id !== selectedNode?.id) selectNode(bad)
    fitView({ nodes: [{ id: bad.id }], maxZoom: 1.2, duration: 300 })
    return true
  }

  // 测试运行：把当前画布序列化成与保存一致的 graph，提交给后端试跑（不落库），
  // 结果分成功/待审核/失败三种状态展示；图校验失败的 400 直接提示 detail
  const doTest = async () => {
    if (blockedByInvalidNode()) return
    setTesting(true); setTestResult(null)
    // 空串按未填处理（后端对必填缺值给 400，文案更准确，前端不重复校验）
    const inputs: Record<string, unknown> = {}
    Object.entries(testInputs).forEach(([k, v]) => { if (v !== undefined && v !== '') inputs[k] = v })
    try { setTestResult(await testRunWorkflow({ graph: toGraph(nodes, edges), inputs }) as any) } catch (e: any) { toast.error(e.response?.data?.detail || '测试失败') } finally { setTesting(false) }
  }

  // 保存：同样序列化 graph；新建走 create，编辑走 update，成功后进详情页；图校验失败的 400 直接提示 detail
  const onSave = async () => {
    if (!name.trim()) { toast.error('请输入工作流名称'); return }
    if (blockedByInvalidNode()) return
    const graph = toGraph(nodes, edges)
    try {
      const saved = isNew ? await createWorkflow({ name, description, graph }) : await updateWorkflow(Number(id), { name, description, graph })
      baseline.current = JSON.stringify({ name, description, graph })
      setDirty(false)
      toast.success('保存成功')
      navigate(`/workflows/${saved.id}`)
    } catch (e) { toast.error(errorText(e, '保存失败')) }
  }

  // 当前选中节点绑定的工具的参数声明：工具节点按声明逐字段渲染参数（docs/17 §3），
  // 与工具页在线测试同一条路径；切工具/切节点时立刻换
  const selectedToolParams = useMemo(() => {
    if (selectedNode?.data?.nodeType !== 'tool') return undefined
    const name = selectedNode.data.config?.tool_name
    return tools.find((t: any) => t.name === name)?.config?.parameters
  }, [selectedNode, tools])

  // 开始节点声明的输入变量：测试运行区按它生成输入框（画布上改了声明，这里立刻跟着变）
  const startVariables = useMemo(() => {
    // 多个开始节点时取第一个"有声明"的：画布上多拖了一个空开始节点不该让已声明的表单突然变空
    const starts = nodes.filter((n) => n.data.nodeType === 'start')
    const start = starts.find((n) => Array.isArray((n.data.config as any)?.variables) && (n.data.config as any).variables.length) ?? starts[0]
    const rows = (start?.data.config as any)?.variables
    if (!Array.isArray(rows)) return []
    return rows
      .filter((v: any) => (v?.name || '').trim())
      .map((v: any) => ({ name: String(v.name).trim(), type: v.type || 'text', description: v.description || '', default: v.default ?? null, required: v.default === undefined || v.default === '' || v.default === null }))
  }, [nodes])

  // 连线的来源节点类型：决定连线配置面板的文案（条件分支 / 循环分支 / 并行分支无分支值）
  const edgeSourceType = selectedEdge ? nodes.find((n) => n.id === selectedEdge.source)?.data?.nodeType : null

  const configContent = (
    <ConfigPanel
      selectedNode={selectedNode}
      selectedEdge={selectedEdge}
      edgeSourceType={edgeSourceType ?? undefined}
      nodeError={nodes.find((n) => n.id === selectedNode?.id)?.data.configError as string | undefined}
      nodeValues={nodeValues}
      onNodeChange={onNodeChange}
      nodeErrorField={nodeErrorField}
      agents={agents}
      tools={tools}
      kbs={kbs}
      toolParams={selectedToolParams}
      edgeLabel={edgeLabel}
      onEdgeLabelChange={changeEdgeLabel}
      onDelete={deleteSelected}
      testVariables={startVariables}
      testInputs={testInputs}
      onTestInputsChange={setTestInputs}
      testing={testing}
      testResult={testResult}
      onTest={doTest}
    />
  )

  if (loadError) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <ErrorState message={loadError} />
        <div className="text-center"><Button variant="secondary" size="md" onClick={() => navigate('/workflows')}>返回工作流列表</Button></div>
      </div>
    )
  }

  // ReactFlow 始终挂载：拖放落点只挂在它上面，空画布时若只渲染提示，第一个节点就拖不进来（2026-09-25 修）。
  // 空态提示浮在画布上且不接收鼠标事件。fitView 只给已有工作流：它会排队到节点加载并测量后才执行；
  // 新建时开着它，拖进第一个节点画布会放大居中到这一个节点上
  const canvas = (
    <div ref={canvasRef} className="relative min-h-0 min-w-0 flex-1 overflow-hidden rounded-xl border border-border bg-secondary">
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
        onNodeClick={onNodeClick} onEdgeClick={onEdgeClick} onPaneClick={onPaneClick} onDrop={onDrop}
        onBeforeDelete={confirmDelete} onDelete={onDeleted}
        onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }} nodeTypes={nodeTypes} fitView={!isNew}
        defaultEdgeOptions={{ style: { stroke: 'var(--border-strong)', strokeWidth: 1.5 }, markerEnd: { type: 'arrowclosed', color: 'var(--border-strong)' } }}>
        <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="var(--border)" />
        <Controls />
        {!isMobile && <MiniMap pannable zoomable nodeColor="var(--bg-soft)" maskColor="rgba(241,245,249,0.7)" />}
      </ReactFlow>
      {nodes.length === 0 && (
        <div className="pointer-events-none absolute left-0 right-0 top-20 text-center text-[13px] text-muted-foreground">
          {isMobile ? '点左上角"节点"添加节点开始编排' : '从节点库拖入或点击节点开始编排'}
        </div>
      )}
    </div>
  )

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="mb-3 flex shrink-0 items-center justify-between gap-3 rounded-xl border border-border bg-card px-3.5 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          {/* 返回同样要过未保存拦截（2026-09-25 前直接跳走，改动静默丢失） */}
          <Button variant="secondary" size="sm" icon={<ArrowLeft />} onClick={() => guardedNavigate(isNew ? '/workflows' : `/workflows/${id}`)}>
            {isMobile ? null : '返回'}
          </Button>
          {isMobile && <Button variant="secondary" size="sm" icon={<Blocks />} onClick={() => setShowPalette(true)}>节点</Button>}
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="工作流名称"
            aria-label="工作流名称"
            className="h-8 text-[13.5px]"
            style={{ width: isMobile ? 130 : 220 }}
          />
          {!isMobile && (
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述（可选，列表与详情页显示）"
              aria-label="描述"
              className="h-8 text-[13.5px]"
              style={{ width: 320 }}
            />
          )}
        </div>
        <Button variant="primary" size="md" icon={<Save />} onClick={onSave}>保存</Button>
      </div>

      {isMobile ? (
        <div className="flex min-h-0 flex-1">{canvas}</div>
      ) : (
        <div className="flex min-h-0 flex-1 gap-3">
          <div className="w-[136px] shrink-0 overflow-auto rounded-xl border border-border bg-card p-2">
            <PaletteList onDragStart={onDragStart} onAdd={(t) => addNode(t)} />
          </div>
          {canvas}
          <div className="w-[320px] shrink-0 overflow-auto rounded-xl border border-border bg-card p-4">
            {configContent}
          </div>
        </div>
      )}

      <Sheet open={isMobile && showPalette} onOpenChange={(open) => { if (!open) setShowPalette(false) }}>
        <SheetContent side="left" className="w-[220px] p-4">
          <SheetHeader className="p-0"><SheetTitle className="text-[14px]">节点库</SheetTitle></SheetHeader>
          <div className="mt-3">
            <PaletteList onDragStart={onDragStart} onAdd={(t) => { addNode(t); setShowPalette(false) }} />
          </div>
        </SheetContent>
      </Sheet>

      <Sheet open={isMobile && !!(selectedNode || selectedEdge)} onOpenChange={(open) => { if (!open) { setSelectedNode(null); setSelectedEdge(null) } }}>
        <SheetContent side="bottom" className="h-[75%] p-4">
          <SheetHeader className="p-0">
            <SheetTitle className="text-[14px]">{selectedNode ? '节点配置 · ' + selectedNode.data.label : selectedEdge ? '连线配置' : '配置'}</SheetTitle>
          </SheetHeader>
          <div className="mt-3 overflow-auto">{configContent}</div>
        </SheetContent>
      </Sheet>

      <Modal
        open={!!pendingDelete}
        size="sm"
        title={`删除 ${pendingDelete?.nodes.length ?? 0} 个节点？`}
        onClose={() => settleDelete(false)}
        footer={
          <>
            <Button variant="ghost" size="md" onClick={() => settleDelete(false)}>取消</Button>
            <Button variant="danger" size="md" onClick={() => settleDelete(true)}>删除</Button>
          </>
        }
      >
        <p className="m-0 text-[13px] text-muted-foreground">
          连同 {pendingDelete?.edges.length ?? 0} 条连线一起删除，删除后不能撤销。
        </p>
      </Modal>
    </div>
  )
}

// 外层用 ReactFlowProvider 包裹：EditorInner 里 useReactFlow 的坐标换算等能力依赖它
export default function WorkflowEditor() {
  return <ReactFlowProvider><EditorInner /></ReactFlowProvider>
}
