import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined, KeyOutlined } from '@ant-design/icons'
import { listApiKeys, createApiKey, toggleApiKey, deleteApiKey } from '../api'

export default function ApiKeys() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setData(await listApiKeys() as any) } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const onSubmit = async (values: any) => {
    try {
      const res: any = await createApiKey(values)
      setCreatedKey(res.key)
      setOpen(false)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e.response?.data?.detail || '创建失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: 'Key', dataIndex: 'key_prefix', render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}</span> },
    { title: '配额', dataIndex: 'quota', width: 90 },
    { title: '已用', dataIndex: 'used', width: 90 },
    { title: '状态', dataIndex: 'is_enabled', width: 90, render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '禁用'}</Tag> },
    { title: '最后使用', dataIndex: 'last_used_at', width: 170, render: (v: string) => v ? new Date(v).toLocaleString() : '-' },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" onClick={async () => { await toggleApiKey(r.id); load() }}>{r.is_enabled ? '禁用' : '启用'}</Button>
        <Popconfirm title="确定删除？" onConfirm={async () => { await deleteApiKey(r.id); load() }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2 style={{ display: 'flex', alignItems: 'center', gap: 8 }}><KeyOutlined /> API Key 管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>生成 Key</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>

      <Modal title="生成 API Key" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ quota: 1000 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：生产环境调用" /></Form.Item>
          <Form.Item name="quota" label="配额(调用次数)"><InputNumber min={1} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="API Key 已生成（仅显示一次，请复制保存）" open={!!createdKey} onCancel={() => setCreatedKey(null)} footer={<Button type="primary" onClick={() => setCreatedKey(null)}>我已保存</Button>}>
        <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, fontFamily: 'monospace', wordBreak: 'break-all' }}>{createdKey}</div>
      </Modal>
    </div>
  )
}
