import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined, ClockCircleOutlined } from '@ant-design/icons'
import { listSchedules, createSchedule, toggleSchedule, deleteSchedule, listWorkflows, OPTIONS_PAGE } from '../api'
import { usePagedList } from '../hooks/usePagedList'

export default function Schedules() {
  const { tableProps, reload } = usePagedList(listSchedules)
  const [workflows, setWorkflows] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()

  useEffect(() => {
    listWorkflows(OPTIONS_PAGE).then((r) => setWorkflows(r.items)).catch((e: any) => message.error(e.response?.data?.detail || '加载工作流失败'))
  }, [])

  const onSubmit = async (values: any) => {
    try {
      let input = {}
      if (values.inputStr) { try { input = JSON.parse(values.inputStr) } catch { message.error('输入 JSON 格式错误'); return } }
      await createSchedule({ name: values.name, workflow_id: values.workflow_id, cron: values.cron, input })
      message.success('创建成功')
      setOpen(false)
      form.resetFields()
      reload()
    } catch (e: any) { message.error(e.response?.data?.detail || '创建失败') }
  }

  const act = async (fn: () => Promise<unknown>, errorText: string) => {
    try { await fn(); reload() } catch (e: any) { message.error(e.response?.data?.detail || errorText) }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '工作流', dataIndex: 'workflow_id', render: (v: number) => workflows.find((w) => w.id === v)?.name || v },
    { title: 'Cron', dataIndex: 'cron', render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
    { title: '状态', dataIndex: 'is_enabled', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '禁用'}</Tag> },
    { title: '最后运行', dataIndex: 'last_run_at', width: 170, render: (v: string) => v ? new Date(v).toLocaleString() : '-' },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" onClick={() => act(() => toggleSchedule(r.id), '操作失败')}>{r.is_enabled ? '禁用' : '启用'}</Button>
        <Popconfirm title="确定删除？" onConfirm={() => act(() => deleteSchedule(r.id), '删除失败')}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><ClockCircleOutlined /> 定时任务</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>新建定时任务</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Modal title="新建定时任务" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="workflow_id" label="工作流" rules={[{ required: true }]}>
            <Select showSearch optionFilterProp="label" options={workflows.map((w: any) => ({ value: w.id, label: w.name }))} />
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
