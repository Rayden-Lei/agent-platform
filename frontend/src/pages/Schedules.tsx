import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { listSchedules, createSchedule, toggleSchedule, deleteSchedule, listWorkflows } from '../api'

export default function Schedules() {
  const [data, setData] = useState<any[]>([])
  const [workflows, setWorkflows] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      setData(await listSchedules() as any)
      setWorkflows(await listWorkflows() as any)
    } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const onSubmit = async (values: any) => {
    try {
      let input = {}
      if (values.inputStr) { try { input = JSON.parse(values.inputStr) } catch { message.error('输入 JSON 格式错误'); return } }
      await createSchedule({ name: values.name, workflow_id: values.workflow_id, cron: values.cron, input })
      message.success('创建成功')
      setOpen(false)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e.response?.data?.detail || '创建失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '工作流', dataIndex: 'workflow_id', render: (v: number) => workflows.find(w => w.id === v)?.name || v },
    { title: 'Cron', dataIndex: 'cron', render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
    { title: '状态', dataIndex: 'is_enabled', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '禁用'}</Tag> },
    { title: '最后运行', dataIndex: 'last_run_at', width: 170, render: (v: string) => v ? new Date(v).toLocaleString() : '-' },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" onClick={async () => { await toggleSchedule(r.id); load() }}>{r.is_enabled ? '禁用' : '启用'}</Button>
        <Popconfirm title="确定删除？" onConfirm={async () => { await deleteSchedule(r.id); load() }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><ClockCircleOutlined /> 定时任务</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>新建定时任务</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>

      <Modal title="新建定时任务" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="workflow_id" label="工作流" rules={[{ required: true }]}>
            <Select options={workflows.map((w: any) => ({ value: w.id, label: w.name }))} />
          </Form.Item>
          <Form.Item name="cron" label="Cron 表达式" rules={[{ required: true }]} tooltip="分 时 日 月 周，如 */5 * * * * 表示每5分钟">
            <Input placeholder="*/5 * * * *" />
          </Form.Item>
          <Form.Item name="inputStr" label="输入(JSON)">
            <Input.TextArea rows={3} placeholder='{"input": "工作流输入"}' />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
