import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, InputNumber } from 'antd'
import { PlusOutlined, ExperimentOutlined } from '@ant-design/icons'
import { listTools, createTool, updateTool, deleteTool, testTool } from '../api'

export default function Tools() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [testTarget, setTestTarget] = useState<any>(null)
  const [testArgs, setTestArgs] = useState('{}')
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setData(await listTools() as any) } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const onSubmit = async (values: any) => {
    try {
      let config = {}
      if (values.type === 'http' && values.configStr) {
        try { config = JSON.parse(values.configStr) } catch { message.error('配置 JSON 格式错误'); return }
      }
      const payload = { name: values.name, description: values.description, type: values.type, config, timeout: values.timeout }
      if (editing) await updateTool(editing.id, payload)
      else await createTool(payload)
      message.success(editing ? '保存成功' : '创建成功')
      setOpen(false)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e.response?.data?.detail || '保存失败') }
  }

  const openCreate = () => { setEditing(null); form.resetFields(); setOpen(true) }
  const openEdit = (r: any) => {
    setEditing(r)
    form.setFieldsValue({ name: r.name, description: r.description, type: r.type, timeout: r.timeout, configStr: JSON.stringify(r.config || {}, null, 2) })
    setOpen(true)
  }

  const doTest = async () => {
    if (!testTarget) return
    setTesting(true)
    try {
      let args = {}
      try { args = JSON.parse(testArgs || '{}') } catch { message.error('参数 JSON 格式错误'); setTesting(false); return }
      const res: any = await testTool(testTarget.id, { args })
      setTestResult(res.data?.result ?? res)
    } catch (e: any) { message.error(e.response?.data?.detail || '测试失败') } finally { setTesting(false) }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '类型', dataIndex: 'type', render: (v: string) => <Tag color={v === 'builtin' ? 'blue' : 'green'}>{v === 'builtin' ? '内置' : 'HTTP'}</Tag> },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '超时(s)', dataIndex: 'timeout', width: 90 },
    {
      title: '操作', render: (_: any, r: any) => (
        <Space>
          <Button size="small" icon={<ExperimentOutlined />} onClick={() => { setTestTarget(r); setTestArgs('{}'); setTestResult(null) }}>测试</Button>
          <Button size="small" onClick={() => openEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={async () => { await deleteTool(r.id); load() }}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>工具管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>新增工具</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>

      <Modal title={editing ? '编辑工具' : '新增工具'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ type: 'builtin', timeout: 30 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述" rules={[{ required: true }]}><Input.TextArea rows={2} /></Form.Item>
          <Form.Item name="type" label="类型"><Select options={[{ value: 'builtin', label: '内置' }, { value: 'http', label: 'HTTP 接口' }]} /></Form.Item>
          <Form.Item noStyle shouldUpdate={(a, b) => a.type !== b.type}>
            {({ getFieldValue }) => getFieldValue('type') === 'http' && (
              <Form.Item name="configStr" label="HTTP 配置(JSON)">
                <Input.TextArea rows={4} placeholder='{"method":"POST","url":"https://...","headers":{}}' />
              </Form.Item>
            )}
          </Form.Item>
          <Form.Item name="timeout" label="超时(秒)"><InputNumber min={1} max={300} /></Form.Item>
        </Form>
      </Modal>

      <Modal title={'测试工具：' + (testTarget?.name || '')} open={!!testTarget} onCancel={() => setTestTarget(null)} onOk={doTest} okText="测试" confirmLoading={testing} destroyOnClose>
        <Form layout="vertical">
          <Form.Item label="参数(JSON)">
            <Input.TextArea value={testArgs} onChange={(e) => setTestArgs(e.target.value)} rows={4} placeholder='{"expression":"2+3"}' />
          </Form.Item>
        </Form>
        {testResult !== null && (
          <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, marginTop: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            <div style={{ fontWeight: 600, marginBottom: 4, fontSize: 13 }}>返回结果：</div>
            <div style={{ fontSize: 13, color: '#334155' }}>{JSON.stringify(testResult, null, 2)}</div>
          </div>
        )}
      </Modal>
    </div>
  )
}
