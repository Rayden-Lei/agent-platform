import { useEffect, useState } from 'react'
import { Alert, Button, Input, Modal, Space, Tag, Typography, message } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import { runWorkflow, type WorkflowRow, type WorkflowRunResult } from '../../api'
import JsonView from '../common/JsonView'
import { errorText } from '../../utils/errors'

// 手动运行工作流：输入 JSON 或文本，结果按成功 / 待审核 / 失败展示，并可跳到本次运行记录看节点日志与审核。
interface Props { workflow: WorkflowRow | null; onClose: () => void; onDone?: () => void }

export default function RunWorkflowModal({ workflow, onClose, onDone }: Props) {
  const [input, setInput] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<WorkflowRunResult | null>(null)
  useEffect(() => { if (workflow) { setInput(''); setResult(null) } }, [workflow])

  const run = async () => {
    if (!workflow) return
    setRunning(true)
    try { setResult(await runWorkflow(workflow.id, { input })); onDone?.() } catch (e) { message.error(errorText(e, '运行失败')) } finally { setRunning(false) }
  }

  return (
    <Modal title={workflow ? `运行工作流：${workflow.name}` : ''} open={!!workflow} onCancel={onClose} width={640} destroyOnHidden
      footer={<Space><Button onClick={onClose}>关闭</Button><Button type="primary" icon={<PlayCircleOutlined />} loading={running} onClick={run}>运行</Button></Space>}>
      <Typography.Text type="secondary" style={{ fontSize: 12 }}>输入会作为起始节点的 input；JSON 字符串会被解析为对象，其他内容按文本传入。运行同步等待结束，长流程请到运行记录页跟踪。</Typography.Text>
      <Input.TextArea value={input} onChange={(e) => setInput(e.target.value)} rows={3} style={{ margin: '8px 0 12px' }} placeholder='{"expression": "2+3*4"}' />
      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {result.status === 'success' && <Alert type="success" showIcon message="运行成功" />}
          {result.status === 'awaiting_review' && <Alert type="warning" showIcon message="等待人工审核" description="流程停在人工审核节点，到运行记录里通过或驳回后继续。" />}
          {result.status !== 'success' && result.status !== 'awaiting_review' && <Alert type="error" showIcon message="运行失败" description={result.error} />}
          {result.run_id && <div>运行记录：<Link to={`/runs/${result.run_id}`}>#{result.run_id}</Link>（节点日志、耗时与 token 在详情页）</div>}
          {result.status === 'success' && <JsonView value={result.output} maxHeight={200} />}
          {result.status === 'awaiting_review' && <JsonView value={result.interrupt} maxHeight={160} />}
          {result.steps?.length > 0 && <div>{result.steps.map((s, i) => <Tag key={i} style={{ marginBottom: 4 }}>{s}</Tag>)}</div>}
        </div>
      )}
    </Modal>
  )
}
