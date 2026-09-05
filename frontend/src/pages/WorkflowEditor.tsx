import { useCallback, useEffect, useRef, useState } from 'react'
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls, MiniMap, addEdge, useNodesState, useEdgesState, useReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Button, Form, Input, Space, message, Empty, Tag, Alert, Divider, Drawer, Grid } from 'antd'
import { ArrowLeftOutlined, SaveOutlined, PlayCircleOutlined, DeleteOutlined, CheckOutlined, MenuOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { getWorkflow, updateWorkflow, createWorkflow, listAgents, listTools, listKBs, testRunWorkflow, OPTIONS_PAGE } from '../api'
import { PALETTE, PaletteList, buildDetail, degreeOf, paletteOf, toGraph } from './workflow/palette'
import { nodeTypes } from './workflow/FlowNode'
import NodeConfigForm, { collectNodeConfig, configToFormValues } from './workflow/NodeConfigForm'
import { useUnsaved } from '../store/unsaved'
import { errorText } from '../utils/errors'

// 工作流画布编辑器（基于 @xyflow/react）：左侧节点库拖拽建节点，中间画布连线编排，
// 右侧为节点/连线配置面板；支持测试运行与保存（新建/更新）。
// 节点库常量与序列化在 ./workflow/palette，节点外观在 ./workflow/FlowNode，配置表单在 ./workflow/NodeConfigForm。
function EditorInner() {
  const navigate = useNavigate()
  const { id } = useParams()
  // isNew：路由无 id 即为新建模式（保存走 create），有 id 为编辑模式（走 update）
  const isNew = !id
  const [name, setName] = useState('未命名工作流')
  const [description, setDescription] = useState('')
  // 未保存标记：把当前画布序列化后与最近一次加载 / 保存的基线比较，只有真正改了才置 dirty
  const setDirty = useUnsaved((s) => s.setDirty)
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
  // 测试运行状态：输入文本 / 结果 / 请求中标记
  const [testInput, setTestInput] = useState('')
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [nodeForm] = Form.useForm()
  const [edgeLabel, setEdgeLabel] = useState('')
  const [showPalette, setShowPalette] = useState(false)
  const { screenToFlowPosition } = useReactFlow()
  const screens = Grid.useBreakpoint()
  const isMobile = !screens.md

  useEffect(() => {
    // 并行加载配置面板下拉数据；编辑模式再拉取工作流详情
    Promise.all([listAgents(OPTIONS_PAGE), listTools(OPTIONS_PAGE), listKBs(OPTIONS_PAGE)])
      .then(([a, t, k]) => { setAgents(a.items); setTools(t.items); setKBs(k.items) })
      .catch((e: any) => message.error(e.response?.data?.detail || '加载选项失败'))
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
      }).catch((e) => { message.error(errorText(e, '加载工作流失败')); navigate('/workflows') })
    } else {
      baseline.current = JSON.stringify({ name: '未命名工作流', description: '', graph: toGraph([], []) })
    }
  }, [id])

  // 名称 / 描述 / 画布任一变化与基线不同即视为未保存；离开编辑器时清掉标记
  useEffect(() => {
    if (baseline.current === null) return
    setDirty(JSON.stringify({ name, description, graph: toGraph(nodes, edges) }) !== baseline.current)
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

  // 拖拽建节点：dragstart 时把节点类型写入 dataTransfer，drop 时按落点坐标创建
  const onDragStart = (event: any, type: string) => { event.dataTransfer.setData('application/reactflow', type); event.dataTransfer.effectAllowed = 'move' }
  const onDrop = (event: any) => {
    event.preventDefault()
    const type = event.dataTransfer.getData('application/reactflow')
    const palette = PALETTE.find((p) => p.type === type)
    if (!palette) return
    // 把鼠标在页面上的坐标换算成画布坐标系，作为新节点的初始位置
    const pos = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    setNodes((nds) => nds.concat({ id: 'node_' + Date.now(), type: 'flow', position: pos, data: { ...palette, nodeType: type, config: {}, detail: '' } }))
  }
  // 从节点拖线到另一节点：默认新建一条连线
  const onConnect = useCallback((conn: any) => setEdges((eds) => addEdge(conn, eds)), [setEdges])

  // 点击节点：记录选中并关闭连线选中，把已存 config 回填到右侧表单
  const onNodeClick = (_: any, node: any) => {
    setSelectedNode(node); setSelectedEdge(null)
    nodeForm.setFieldsValue(configToFormValues(node.data.config))
  }
  // 点击连线：编辑分支值（label）；点击空白处取消所有选中
  const onEdgeClick = (_: any, edge: any) => { setSelectedEdge(edge); setSelectedNode(null); setEdgeLabel(edge.label || '') }
  const onPaneClick = () => { setSelectedNode(null); setSelectedEdge(null) }

  // 保存节点配置：收集表单为 config，更新节点 data 并重建摘要
  const saveNode = () => {
    if (!selectedNode) return
    const collected = collectNodeConfig(selectedNode.data.nodeType, nodeForm.getFieldsValue())
    if ('error' in collected) { message.error(collected.error); return }
    const detail = buildDetail(selectedNode.data.nodeType, collected.config, agents, tools, degreeOf(selectedNode.id, edges))
    setNodes((nds) => nds.map((n) => (n.id === selectedNode.id ? { ...n, data: { ...n.data, config: collected.config, detail } } : n)))
    message.success('配置已应用')
  }

  // 保存连线：把输入的分支值写为边 label（条件分支为 true/false，循环分支为 loop/exit）
  const saveEdge = () => { if (!selectedEdge) return; setEdges((eds) => eds.map((e) => (e.id === selectedEdge.id ? { ...e, label: edgeLabel || undefined } : e))); message.success('分支已更新') }

  // 删除当前选中：删节点时一并清理挂在该节点上的入/出连线
  const deleteSelected = () => {
    if (selectedNode) {
      const nid = selectedNode.id
      setNodes((nds) => nds.filter((n) => n.id !== nid))
      setEdges((eds) => eds.filter((e) => e.source !== nid && e.target !== nid))
      setSelectedNode(null)
    } else if (selectedEdge) {
      setEdges((eds) => eds.filter((e) => e.id !== selectedEdge.id))
      setSelectedEdge(null)
    }
  }

  // 测试运行：把当前画布序列化成与保存一致的 graph，提交给后端试跑（不落库），
  // 结果分成功/待审核/失败三种状态展示；图校验失败的 400 直接提示 detail
  const doTest = async () => {
    setTesting(true); setTestResult(null)
    try { setTestResult(await testRunWorkflow({ graph: toGraph(nodes, edges), input: testInput }) as any) } catch (e: any) { message.error(e.response?.data?.detail || '测试失败') } finally { setTesting(false) }
  }

  // 保存：同样序列化 graph；新建走 create，编辑走 update，成功后进详情页；图校验失败的 400 直接提示 detail
  const onSave = async () => {
    if (!name.trim()) { message.error('请输入工作流名称'); return }
    const graph = toGraph(nodes, edges)
    try {
      const saved = isNew ? await createWorkflow({ name, description, graph }) : await updateWorkflow(Number(id), { name, description, graph })
      baseline.current = JSON.stringify({ name, description, graph })
      setDirty(false)
      message.success('保存成功'); navigate(`/workflows/${saved.id}`)
    } catch (e) { message.error(errorText(e, '保存失败')) }
  }

  // 连线的来源节点类型：决定连线配置面板的文案（条件分支 / 循环分支 / 并行分支无分支值）
  const edgeSourceType = selectedEdge ? nodes.find((n) => n.id === selectedEdge.source)?.data?.nodeType : null

  const configContent = (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ flexShrink: 0 }}>
        {selectedNode ? (
          <>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>节点配置 · {selectedNode.data.label}</div>
            <NodeConfigForm nodeType={selectedNode.data.nodeType} form={nodeForm} agents={agents} tools={tools} kbs={kbs} />
            <Space style={{ marginTop: 12 }}>
              <Button type="primary" size="small" icon={<CheckOutlined />} onClick={saveNode}>应用配置</Button>
              <Button danger size="small" icon={<DeleteOutlined />} onClick={deleteSelected}>删除节点</Button>
            </Space>
          </>
        ) : selectedEdge ? (
          <>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>连线配置 · {edgeSourceType === 'loop' ? '循环分支' : edgeSourceType === 'parallel' ? '并行分支' : '条件分支'}</div>
            {edgeSourceType === 'parallel' ? (
              <div style={{ color: '#9ca3af', fontSize: 13 }}>并行节点的出边不需要分支值，每条出边就是一条并发分支。</div>
            ) : (
              <Form layout="vertical" size="small">
                <Form.Item label={edgeSourceType === 'loop' ? '分支值(loop=回环 / exit=退出)' : '分支值(true/false)'}>
                  <Input value={edgeLabel} onChange={(e) => setEdgeLabel(e.target.value)} placeholder={edgeSourceType === 'loop' ? 'loop 或 exit' : 'true 或 false'} />
                </Form.Item>
              </Form>
            )}
            <Space style={{ marginTop: 12 }}>
              {edgeSourceType !== 'parallel' && <Button type="primary" size="small" icon={<CheckOutlined />} onClick={saveEdge}>应用</Button>}
              <Button danger size="small" icon={<DeleteOutlined />} onClick={deleteSelected}>删除连线</Button>
            </Space>
          </>
        ) : (
          <div style={{ color: '#9ca3af', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>点击画布中的节点或连线<br />在右侧进行配置</div>
        )}
      </div>
      <Divider style={{ margin: '16px 0' }} />
      {/* 测试运行区：输入工作流入参后试跑，不保存到工作流定义 */}
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}><PlayCircleOutlined /> 测试运行</div>
      <Input.TextArea size="small" value={testInput} onChange={(e) => setTestInput(e.target.value)} rows={2} placeholder='{"expression": "2+3*4"}' />
      <Button type="primary" size="small" block style={{ marginTop: 8 }} icon={<PlayCircleOutlined />} loading={testing} onClick={doTest}>运行</Button>
      {testResult && (
        <div style={{ marginTop: 12 }}>
          {testResult.status === 'success' ? (
            <>
              <Alert type="success" message="运行成功" style={{ marginBottom: 8 }} showIcon />
              <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>输出：</div>
              <pre style={{ background: '#f8fafc', padding: 8, borderRadius: 6, fontSize: 12, maxHeight: 120, overflow: 'auto', margin: 0 }}>{JSON.stringify(testResult.output, null, 2)}</pre>
              {testResult.steps?.length > 0 && <div style={{ marginTop: 8 }}>{testResult.steps.map((s: string, i: number) => <Tag key={i} style={{ marginBottom: 4 }}>{s}</Tag>)}</div>}
            </>
          ) : testResult.status === 'awaiting_review' ? (
            <Alert type="warning" message="等待人工审核" description={JSON.stringify(testResult.interrupt)} showIcon />
          ) : <Alert type="error" message="运行失败" description={testResult.error} showIcon />}
        </div>
      )}
    </div>
  )

  const canvas = (
    <div style={{ flex: 1, border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden', background: '#f8fafc', minWidth: 0, minHeight: 0 }}>
      {/* 空画布提示拖入节点；ReactFlow 挂载拖拽落点/点击/连线等交互 */}
      {nodes.length === 0 ? <Empty style={{ marginTop: 80 }} description="从节点库拖入节点开始编排" /> : (
        <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect}
          onNodeClick={onNodeClick} onEdgeClick={onEdgeClick} onPaneClick={onPaneClick} onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }} nodeTypes={nodeTypes} fitView
          defaultEdgeOptions={{ style: { stroke: '#94a3b8', strokeWidth: 1.5 }, markerEnd: { type: 'arrowclosed', color: '#94a3b8' } }}>
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="#dbe2ea" />
          <Controls />
          {!isMobile && <MiniMap pannable zoomable nodeColor="#e2e8f0" maskColor="rgba(241,245,249,0.7)" />}
        </ReactFlow>
      )}
    </div>
  )

  return (
    <div style={{ display: 'flex', flex: 1, flexDirection: 'column', minHeight: 0 }}>
      <div style={{ padding: '10px 14px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', border: '1px solid #e5e7eb', borderRadius: 10, background: '#fff', marginBottom: 12, flexShrink: 0 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(isNew ? '/workflows' : `/workflows/${id}`)}>{isMobile ? '' : '返回'}</Button>
          {isMobile && <Button icon={<MenuOutlined />} onClick={() => setShowPalette(true)}>节点</Button>}
          <Input value={name} onChange={(e) => setName(e.target.value)} style={{ width: isMobile ? 130 : 220 }} placeholder="工作流名称" />
          {!isMobile && <Input value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: 320 }} placeholder="描述（可选，列表与详情页显示）" />}
        </Space>
        <Button type="primary" icon={<SaveOutlined />} onClick={onSave}>保存</Button>
      </div>

      {isMobile ? (
        <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
          {canvas}
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', gap: 12, minHeight: 0 }}>
          <div style={{ width: 160, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 12, flexShrink: 0, overflow: 'auto' }}>
            <PaletteList onDragStart={onDragStart} />
          </div>
          {canvas}
          <div style={{ width: 320, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 16, flexShrink: 0, overflow: 'auto' }}>
            {configContent}
          </div>
        </div>
      )}

      <Drawer title="节点库" placement="left" open={isMobile && showPalette} onClose={() => setShowPalette(false)} width={220}>
        <PaletteList onDragStart={onDragStart} />
      </Drawer>

      <Drawer title={selectedNode ? '节点配置 · ' + selectedNode.data.label : selectedEdge ? '连线配置' : '配置'} placement="bottom" open={isMobile && !!(selectedNode || selectedEdge)} onClose={() => { setSelectedNode(null); setSelectedEdge(null) }} height="75%">
        {configContent}
      </Drawer>
    </div>
  )
}

// 外层用 ReactFlowProvider 包裹：EditorInner 里 useReactFlow 的坐标换算等能力依赖它
export default function WorkflowEditor() {
  return <ReactFlowProvider><EditorInner /></ReactFlowProvider>
}
