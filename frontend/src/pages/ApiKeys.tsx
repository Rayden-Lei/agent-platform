import { useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined, KeyOutlined } from '@ant-design/icons'
import { listApiKeys, createApiKey, toggleApiKey, deleteApiKey } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// API Key 管理页：生成调用方密钥（明文仅创建时返回一次）、启用/禁用、删除。
// 列表展示配额与已用量，key 本身只显示前缀，防止泄露完整密钥。
export default function ApiKeys() {
  const { tableProps, reload } = usePagedList(listApiKeys)
  const [open, setOpen] = useState(false)
  // 创建成功后服务端返回的明文 Key，展示后用户复制保存，刷新即不可再见
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [form] = Form.useForm()

  // 新增/编辑共用提交：editing 非空走更新接口，否则走创建接口；成功后关弹窗并刷新列表
  const onSubmit = async (values: any) => {
    try {
      // 创建接口返回一次明文 key，存入 createdKey 供"仅显示一次"弹窗展示
      const res: any = await createApiKey(values)
      setCreatedKey(res.key)
      setOpen(false)
      form.resetFields()
      reload()
    } catch (e: any) { message.error(e.response?.data?.detail || '创建失败') }
  }

  // 通用操作包装：执行一次写操作（启用/禁用/删除）→ 成功后刷新列表，失败统一取后端 detail 提示
  const act = async (fn: () => Promise<unknown>, errorText: string) => {
    try { await fn(); reload() } catch (e: any) { message.error(e.response?.data?.detail || errorText) }
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
        <Button size="small" onClick={() => act(() => toggleApiKey(r.id), '操作失败')}>{r.is_enabled ? '禁用' : '启用'}</Button>
        <Popconfirm title="确定删除？" onConfirm={() => act(() => deleteApiKey(r.id), '删除失败')}><Button size="small" danger>删除</Button></Popconfirm>
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
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Modal title="生成 API Key" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ quota: 1000 }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input placeholder="如：生产环境调用" /></Form.Item>
          <Form.Item name="quota" label="配额(调用次数)"><InputNumber min={1} /></Form.Item>
        </Form>
      </Modal>

      <Modal title="API Key 已生成（仅显示一次，请复制保存）" open={!!createdKey} onCancel={() => setCreatedKey(null)} footer={<Button type="primary" onClick={() => setCreatedKey(null)}>我已保存</Button>}>
        <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, fontFamily: 'monospace', wordBreak: 'break-all' }}>{createdKey}</div>
        <div style={{ marginTop: 10, fontSize: 12, color: '#64748b', lineHeight: 1.7 }}>
          调用方式：请求头 <code>Authorization: Bearer {'<key>'}</code>。可调用对话、会话、工作流运行接口，管理类接口不接受 API Key；每次请求消耗 1 次配额。
        </div>
      </Modal>
    </div>
  )
}
