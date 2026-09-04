import { useState } from 'react'
import { Table, Button, Modal, Form, Input, message, Popconfirm, Space, Tag, Card } from 'antd'
import { PlusOutlined, PlayCircleOutlined, EditOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listWorkflows, deleteWorkflow, runWorkflow } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// 工作流列表页：展示已保存的工作流；编辑跳转到画布编辑器，运行弹窗可立即执行一次
// （输入 JSON/文本），删除需二次确认。
export default function Workflows() {
  const { tableProps, reload } = usePagedList(listWorkflows)
  // 运行弹窗状态：目标工作流 / 输入文本 / 本次运行结果
  const [runWf, setRunWf] = useState<any>(null)
  const [runInput, setRunInput] = useState('')
  const [runResult, setRunResult] = useState<any>(null)
  const navigate = useNavigate()

  // 手动触发一次运行：入参是文本（可直接是 JSON 字符串），结果在弹窗内展示状态/输出/错误
  const doRun = async () => {
    try {
      const res: any = await runWorkflow(runWf.id, { input: runInput })
      setRunResult(res)
    } catch (e: any) { message.error(e.response?.data?.detail || '运行失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'published' ? 'green' : 'orange'}>{v}</Tag> },
    { title: '版本', dataIndex: 'version', width: 70 },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" icon={<EditOutlined />} onClick={() => navigate('/workflows/' + r.id + '/edit')}>编辑</Button>
        {/* 打开运行弹窗并重置输入与上次结果 */}
        <Button size="small" icon={<PlayCircleOutlined />} onClick={() => { setRunWf(r); setRunInput(''); setRunResult(null) }}>运行</Button>
        <Popconfirm title="确定删除？" onConfirm={async () => { try { await deleteWorkflow(r.id); reload() } catch (e: any) { message.error(e.response?.data?.detail || '删除失败') } }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>工作流</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/workflows/new')}>新建工作流</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Modal title={'运行工作流：' + (runWf?.name || '')} open={!!runWf} onCancel={() => setRunWf(null)} onOk={doRun} okText="运行">
        <Form layout="vertical">
          <Form.Item label="输入(JSON 或文本)">
            <Input.TextArea value={runInput} onChange={(e) => setRunInput(e.target.value)} rows={3} placeholder='{"expression": "2+3*4"}' />
          </Form.Item>
        </Form>
        {runResult && (
          <Card size="small" style={{ marginTop: 12 }}>
            <div>状态：<Tag color={runResult.status === 'success' ? 'green' : runResult.status === 'awaiting_review' ? 'orange' : 'red'}>{runResult.status}</Tag></div>
            <div>输出：{JSON.stringify(runResult.output)}</div>
            {runResult.error && <div style={{ color: 'red' }}>错误：{runResult.error}</div>}
          </Card>
        )}
      </Modal>
    </div>
  )
}
