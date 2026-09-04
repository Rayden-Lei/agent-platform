import { useCallback, useEffect, useState } from 'react'
import { ReactFlow, ReactFlowProvider, Background, BackgroundVariant, Controls, MiniMap, addEdge, useNodesState, useEdgesState, Handle, Position, useReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { Button, Form, Input, InputNumber, Select, Space, message, Empty, Tag, Alert, Divider, Drawer, Grid } from 'antd'
import { ArrowLeftOutlined, SaveOutlined, PlayCircleOutlined, CheckCircleOutlined, RobotOutlined, ToolOutlined, BranchesOutlined, DeleteOutlined, CheckOutlined, MenuOutlined, DatabaseOutlined, CodeOutlined, ApiOutlined, SyncOutlined, AuditOutlined } from '@ant-design/icons'
import { useNavigate, useParams } from 'react-router-dom'
import { getWorkflow, updateWorkflow, createWorkflow, listAgents, listTools, listKBs, testRunWorkflow, OPTIONS_PAGE } from '../api'

const PALETTE = [
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
]

function FlowNode({ data, selected }: any) {
  return (
    <div style={{ background: '#fff', border: selected ? '2px solid ' + data.color : '1px solid #e5e7eb', borderRadius: 10, boxShadow: selected ? '0 6px 20px rgba(15,23,42,0.16)' : '0 2px 6px rgba(15,23,42,0.06)', minWidth: 150, cursor: 'pointer', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px' }}>
        <div style={{ width: 30, height: 30, borderRadius: 8, background: data.color, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 15, flexShrink: 0 }}>{data.icon}</div>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13, color: '#1f2937', lineHeight: 1.3 }}>{data.label}</div>
          {data.detail && <div style={{ fontSize: 11, color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 140 }}>{data.detail}</div>}
        </div>
      </div>
      <Handle type="target" position={Position.Left} style={{ width: 9, height: 9, background: '#fff', border: '2px solid ' + data.color }} />
      <Handle type="source" position={Position.Right} style={{ width: 9, height: 9, background: '#fff', border: '2px solid ' + data.color }} />
    </div>
  )
}

const nodeTypes = { flow: FlowNode }

function buildDetail(nodeType: string, config: any, agents: any[], tools: any[]) {
  if (nodeType === 'agent') { const a = agents.find((x: any) => x.id === config.agent_id); return a ? a.name : '未选择智能体' }
  if (nodeType === 'tool') return config.tool_name || '未选择工具'
  if (nodeType === 'condition') return config.expression || '未设表达式'
  if (nodeType === 'kb_retrieval') return config.kb_id ? '知识库检索' : '未选择知识库'
  if (nodeType === 'code') return '代码执行'
  if (nodeType === 'http') return config.url || '未配置URL'
  if (nodeType === 'loop') return config.expression ? '条件循环' : '循环 ' + (config.count || 1) + ' 次'
  if (nodeType === 'human_review') return config.instruction || '人工审核'
  return ''
}

function EditorInner() {
  const navigate = useNavigate()
  const { id } = useParams()
  const isNew = !id
  const [name, setName] = useState('未命名工作流')
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [agents, setAgents] = useState<any[]>([])
  const [tools, setTools] = useState<any[]>([])
  const [kbs, setKBs] = useState<any[]>([])
  const [selectedNode, setSelectedNode] = useState<any>(null)
  const [selectedEdge, setSelectedEdge] = useState<any>(null)
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
    Promise.all([listAgents(OPTIONS_PAGE), listTools(OPTIONS_PAGE), listKBs(OPTIONS_PAGE)])
      .then(([a, t, k]) => { setAgents(a.items); setTools(t.items); setKBs(k.items) })
      .catch((e: any) => message.error(e.response?.data?.detail || '加载选项失败'))
    if (!isNew && id) {
      getWorkflow(Number(id)).then((wf: any) => {
        setName(wf.name)
        const ns = (wf.graph?.nodes || []).map((n: any) => {
          const palette = PALETTE.find((p) => p.type === n.type)
          return { id: n.id, type: 'flow', position: { x: n.position?.x ?? 80, y: n.position?.y ?? 80 }, data: { ...palette, nodeType: n.type, config: n.config || {}, detail: buildDetail(n.type, n.config || {}, [], []) } }
        })
        const es = (wf.graph?.edges || []).map((e: any, i: number) => ({ id: 'e' + i, source: e.from, target: e.to, label: e.when || undefined }))
        setNodes(ns)
        setEdges(es)
        setNodes((prev) => prev.map((n) => ({ ...n, data: { ...n.data, detail: buildDetail(n.data.nodeType, n.data.config, agents, tools) } })))
      })
    }
  }, [id])

  const onDragStart = (event: any, type: string) => { event.dataTransfer.setData('application/reactflow', type); event.dataTransfer.effectAllowed = 'move' }
  const onDrop = (event: any) => {
    event.preventDefault()
    const type = event.dataTransfer.getData('application/reactflow')
    const palette = PALETTE.find((p) => p.type === type)
    if (!palette) return
    const pos = screenToFlowPosition({ x: event.clientX, y: event.clientY })
    setNodes((nds) => nds.concat({ id: 'node_' + Date.now(), type: 'flow', position: pos, data: { ...palette, nodeType: type, config: {}, detail: '' } }))
  }
  const onConnect = useCallback((conn: any) => setEdges((eds) => addEdge(conn, eds)), [setEdges])

  const onNodeClick = (_: any, node: any) => {
    setSelectedNode(node); setSelectedEdge(null)
    nodeForm.setFieldsValue({ agent_id: node.data.config?.agent_id, tool_name: node.data.config?.tool_name, expression: node.data.config?.expression, prompt: node.data.config?.prompt, argsStr: node.data.config?.args ? JSON.stringify(node.data.config.args) : '', kb_id: node.data.config?.kb_id, top_k: node.data.config?.top_k || 4, code: node.data.config?.code, url: node.data.config?.url, method: node.data.config?.method || 'POST', count: node.data.config?.count || 1, instruction: node.data.config?.instruction, input_ref: node.data.config?.input_ref, output_field: node.data.config?.output_field })
  }
  const onEdgeClick = (_: any, edge: any) => { setSelectedEdge(edge); setSelectedNode(null); setEdgeLabel(edge.label || '') }
  const onPaneClick = () => { setSelectedNode(null); setSelectedEdge(null) }

  const saveNode = () => {
    if (!selectedNode) return
    const vals = nodeForm.getFieldsValue()
    let config: any = {}
    if (selectedNode.data.nodeType === 'agent') { config = { agent_id: vals.agent_id }; if (vals.prompt) config.prompt = vals.prompt }
    if (selectedNode.data.nodeType === 'tool') { config = { tool_name: vals.tool_name }; if (vals.argsStr) { try { config.args = JSON.parse(vals.argsStr) } catch { message.error('参数 JSON 格式错误'); return } } }
    if (selectedNode.data.nodeType === 'condition') config = { expression: vals.expression }
    if (selectedNode.data.nodeType === 'kb_retrieval') config = { kb_id: vals.kb_id, top_k: vals.top_k || 4 }
    if (selectedNode.data.nodeType === 'code') config = { code: vals.code || '' }
    if (selectedNode.data.nodeType === 'http') config = { url: vals.url, method: vals.method || 'POST' }
    if (selectedNode.data.nodeType === 'loop') { config = { count: vals.count || 1 }; if (vals.expression) config.expression = vals.expression }
    if (selectedNode.data.nodeType === 'human_review') config = { instruction: vals.instruction || '请审核' }
    if (['agent', 'tool', 'kb_retrieval', 'code', 'http', 'human_review', 'loop', 'condition'].includes(selectedNode.data.nodeType)) {
      if (vals.input_ref) config.input_ref = vals.input_ref
      if (vals.output_field) config.output_field = vals.output_field
    }
    const detail = buildDetail(selectedNode.data.nodeType, config, agents, tools)
    setNodes((nds) => nds.map((n) => (n.id === selectedNode.id ? { ...n, data: { ...n.data, config, detail } } : n)))
    message.success('配置已应用')
  }

  const saveEdge = () => { if (!selectedEdge) return; setEdges((eds) => eds.map((e) => (e.id === selectedEdge.id ? { ...e, label: edgeLabel || undefined } : e))); message.success('分支已更新') }

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

  const doTest = async () => {
    const graph = { nodes: nodes.map((n) => ({ id: n.id, type: n.data.nodeType, config: n.data.config, position: n.position })), edges: edges.map((e) => ({ from: e.source, to: e.target, when: e.label || undefined })) }
    setTesting(true); setTestResult(null)
    try { setTestResult(await testRunWorkflow({ graph, input: testInput }) as any) } catch (e: any) { message.error(e.response?.data?.detail || '测试失败') } finally { setTesting(false) }
  }

  const onSave = async () => {
    if (!name.trim()) { message.error('请输入工作流名称'); return }
    const graph = { nodes: nodes.map((n) => ({ id: n.id, type: n.data.nodeType, config: n.data.config, position: n.position })), edges: edges.map((e) => ({ from: e.source, to: e.target, when: e.label || undefined })) }
    try {
      if (isNew) await createWorkflow({ name, description: '', graph })
      else await updateWorkflow(Number(id), { name, description: '', graph })
      message.success('保存成功'); navigate('/workflows')
    } catch (e: any) { message.error(e.response?.data?.detail || '保存失败') }
  }

  const edgeSourceType = selectedEdge ? nodes.find((n) => n.id === selectedEdge.source)?.data?.nodeType : null

  const paletteContent = (
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
      <div style={{ color: '#9ca3af', fontSize: 11, marginTop: 4, lineHeight: 1.5 }}>拖入画布编排；点击节点/连线配置。</div>
    </div>
  )

  const configContent = (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ flexShrink: 0 }}>
        {selectedNode ? (
          <>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>节点配置 · {selectedNode.data.label}</div>
            <Form form={nodeForm} layout="vertical" size="small">
              {selectedNode.data.nodeType === 'agent' && (<>
                <Form.Item name="agent_id" label="选择智能体"><Select options={agents.map((a: any) => ({ value: a.id, label: a.name }))} placeholder="选择智能体" /></Form.Item>
                <Form.Item name="prompt" label="提示词覆盖(可选)"><Input.TextArea rows={2} placeholder="留空则用默认提示词" /></Form.Item>
              </>)}
              {selectedNode.data.nodeType === 'tool' && (<>
                <Form.Item name="tool_name" label="选择工具"><Select options={tools.map((t: any) => ({ value: t.name, label: t.name }))} placeholder="选择工具" /></Form.Item>
                <Form.Item name="argsStr" label="参数(JSON,可选)"><Input.TextArea rows={2} placeholder='留空则用上游输出' /></Form.Item>
              </>)}
              {selectedNode.data.nodeType === 'condition' && <Form.Item name="expression" label="条件表达式"><Input placeholder="len(input) > 5" /></Form.Item>}
              {selectedNode.data.nodeType === 'kb_retrieval' && (<>
                <Form.Item name="kb_id" label="选择知识库"><Select options={kbs.map((k: any) => ({ value: k.id, label: k.name }))} placeholder="选择知识库" /></Form.Item>
                <Form.Item name="top_k" label="召回数量 Top K"><InputNumber min={1} max={20} /></Form.Item>
              </>)}
              {selectedNode.data.nodeType === 'code' && <Form.Item name="code" label="Python 代码"><Input.TextArea rows={6} placeholder={"可用变量 input(上游输出)，把结果赋给 result"} /></Form.Item>}
              {selectedNode.data.nodeType === 'http' && (<>
                <Form.Item name="url" label="请求 URL"><Input placeholder="https://api.example.com/xxx" /></Form.Item>
                <Form.Item name="method" label="方法"><Select options={[{ value: 'GET', label: 'GET' }, { value: 'POST', label: 'POST' }]} /></Form.Item>
              </>)}
              {selectedNode.data.nodeType === 'loop' && (<>
                <Form.Item name="count" label="循环次数"><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item>
                <Form.Item name="expression" label="循环条件(可选,优先于次数)"><Input placeholder="如 len(output) < 10" /></Form.Item>
              </>)}
              {selectedNode.data.nodeType === 'human_review' && <Form.Item name="instruction" label="审核说明"><Input placeholder="请人工确认后通过" /></Form.Item>}
              {['agent', 'tool', 'kb_retrieval', 'code', 'http', 'human_review', 'loop', 'condition'].includes(selectedNode.data.nodeType) && (<>
                <Form.Item name="input_ref" label="输入引用(可选)"><Input placeholder="留空=上游输出；如 {{input}} 或 {{node_xxx.字段}}" /></Form.Item>
                <Form.Item name="output_field" label="输出字段(可选)"><Input placeholder="留空=完整输出；如 data.items" /></Form.Item>
              </>)}
              {(selectedNode.data.nodeType === 'start' || selectedNode.data.nodeType === 'end') && <div style={{ color: '#9ca3af' }}>该节点无需配置。</div>}
            </Form>
            <Space style={{ marginTop: 12 }}>
              <Button type="primary" size="small" icon={<CheckOutlined />} onClick={saveNode}>应用配置</Button>
              <Button danger size="small" icon={<DeleteOutlined />} onClick={deleteSelected}>删除节点</Button>
            </Space>
          </>
        ) : selectedEdge ? (
          <>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>连线配置 · {edgeSourceType === 'loop' ? '循环分支' : '条件分支'}</div>
            <Form layout="vertical" size="small">
              <Form.Item label={edgeSourceType === 'loop' ? '分支值(loop=回环 / exit=退出)' : '分支值(true/false)'}>
                <Input value={edgeLabel} onChange={(e) => setEdgeLabel(e.target.value)} placeholder={edgeSourceType === 'loop' ? 'loop 或 exit' : 'true 或 false'} />
              </Form.Item>
            </Form>
            <Space style={{ marginTop: 12 }}>
              <Button type="primary" size="small" icon={<CheckOutlined />} onClick={saveEdge}>应用</Button>
              <Button danger size="small" icon={<DeleteOutlined />} onClick={deleteSelected}>删除连线</Button>
            </Space>
          </>
        ) : (
          <div style={{ color: '#9ca3af', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>点击画布中的节点或连线<br />在右侧进行配置</div>
        )}
      </div>
      <Divider style={{ margin: '16px 0' }} />
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
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/workflows')}>{isMobile ? '' : '返回'}</Button>
          {isMobile && <Button icon={<MenuOutlined />} onClick={() => setShowPalette(true)}>节点</Button>}
          <Input value={name} onChange={(e) => setName(e.target.value)} style={{ width: isMobile ? 130 : 220 }} placeholder="工作流名称" />
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
            {paletteContent}
          </div>
          {canvas}
          <div style={{ width: 320, background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: 16, flexShrink: 0, overflow: 'auto' }}>
            {configContent}
          </div>
        </div>
      )}

      <Drawer title="节点库" placement="left" open={isMobile && showPalette} onClose={() => setShowPalette(false)} width={220}>
        {paletteContent}
      </Drawer>

      <Drawer title={selectedNode ? '节点配置 · ' + selectedNode.data.label : selectedEdge ? '连线配置' : '配置'} placement="bottom" open={isMobile && !!(selectedNode || selectedEdge)} onClose={() => { setSelectedNode(null); setSelectedEdge(null) }} height="75%">
        {configContent}
      </Drawer>
    </div>
  )
}

export default function WorkflowEditor() {
  return <ReactFlowProvider><EditorInner /></ReactFlowProvider>
}
