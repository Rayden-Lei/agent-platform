import { Alert, Button, Divider, Form, Input, Space, Tag } from 'antd'
import type { FormInstance } from 'antd'
import { DeleteOutlined, PlayCircleOutlined } from '@ant-design/icons'
import NodeConfigForm from './NodeConfigForm'

// 工作流编辑器右侧面板：节点配置与连线分支值（改动即写回，没有"应用"按钮）/ 测试运行。
// 从 WorkflowEditor 拆出（docs/15 WF-01 时该文件已近 300 行）；状态都在编辑器页面里，这里只渲染与回调。
interface Props {
  selectedNode: any
  selectedEdge: any
  edgeSourceType?: string
  nodeError?: string // 当前节点表单校验不过的原因（不写回节点、保存会被拦）
  nodeForm: FormInstance
  agents: any[]
  tools: any[]
  kbs: any[]
  onNodeValuesChange: () => void
  edgeLabel: string
  onEdgeLabelChange: (value: string) => void // 随输入直接写回连线，与节点配置一致
  onDelete: () => void // 走 React Flow 的 deleteElements，和 Backspace 一样先过删除确认
  testInput: string
  onTestInputChange: (value: string) => void
  testing: boolean
  testResult: any
  onTest: () => void
}

export default function ConfigPanel(p: Props) {
  const isLoopEdge = p.edgeSourceType === 'loop'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ flexShrink: 0 }}>
        {p.selectedNode ? (
          <>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>节点配置 · {p.selectedNode.data.label}</div>
            <NodeConfigForm nodeType={p.selectedNode.data.nodeType} form={p.nodeForm} agents={p.agents} tools={p.tools} kbs={p.kbs} onValuesChange={p.onNodeValuesChange} />
            {p.nodeError && <Alert type="error" showIcon style={{ marginTop: 8 }} message={`${p.nodeError}：改正前不会写回节点，保存会被拦下`} />}
            <Space style={{ marginTop: 12 }}>
              <Button danger size="small" icon={<DeleteOutlined />} onClick={p.onDelete}>删除节点</Button>
            </Space>
          </>
        ) : p.selectedEdge ? (
          <>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 12 }}>连线配置 · {isLoopEdge ? '循环分支' : p.edgeSourceType === 'parallel' ? '并行分支' : '条件分支'}</div>
            {p.edgeSourceType === 'parallel' ? (
              <div style={{ color: '#9ca3af', fontSize: 13 }}>并行节点的出边不需要分支值，每条出边就是一条并发分支。</div>
            ) : (
              <Form layout="vertical" size="small">
                <Form.Item label={isLoopEdge ? '分支值(loop=回环 / exit=退出)' : '分支值(true/false)'}>
                  <Input value={p.edgeLabel} onChange={(e) => p.onEdgeLabelChange(e.target.value)} placeholder={isLoopEdge ? 'loop 或 exit' : 'true 或 false'} />
                </Form.Item>
              </Form>
            )}
            <Space style={{ marginTop: 12 }}>
              <Button danger size="small" icon={<DeleteOutlined />} onClick={p.onDelete}>删除连线</Button>
            </Space>
          </>
        ) : (
          <div style={{ color: '#9ca3af', fontSize: 13, padding: '20px 0', textAlign: 'center' }}>点击画布中的节点或连线<br />在右侧进行配置</div>
        )}
      </div>
      <Divider style={{ margin: '16px 0' }} />
      {/* 测试运行区：输入工作流入参后试跑，不保存到工作流定义 */}
      <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6 }}><PlayCircleOutlined /> 测试运行</div>
      <Input.TextArea size="small" value={p.testInput} onChange={(e) => p.onTestInputChange(e.target.value)} rows={2} placeholder='{"expression": "2+3*4"}' />
      <Button type="primary" size="small" block style={{ marginTop: 8 }} icon={<PlayCircleOutlined />} loading={p.testing} onClick={p.onTest}>运行</Button>
      {p.testResult && (
        <div style={{ marginTop: 12 }}>
          {p.testResult.status === 'success' ? (
            <>
              <Alert type="success" message="运行成功" style={{ marginBottom: 8 }} showIcon />
              <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 4 }}>输出：</div>
              <pre style={{ background: '#f8fafc', padding: 8, borderRadius: 6, fontSize: 12, maxHeight: 120, overflow: 'auto', margin: 0 }}>{JSON.stringify(p.testResult.output, null, 2)}</pre>
              {p.testResult.steps?.length > 0 && <div style={{ marginTop: 8 }}>{p.testResult.steps.map((s: string, i: number) => <Tag key={i} style={{ marginBottom: 4 }}>{s}</Tag>)}</div>}
            </>
          ) : p.testResult.status === 'awaiting_review' ? (
            <Alert type="warning" message="等待人工审核" description={JSON.stringify(p.testResult.interrupt)} showIcon />
          ) : <Alert type="error" message="运行失败" description={p.testResult.error} showIcon />}
        </div>
      )}
    </div>
  )
}
