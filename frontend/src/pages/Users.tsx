import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, Switch } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listUsers, createUser, updateUser, deleteUser } from '../api'

export default function Users() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setData(await listUsers() as any) } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const onSubmit = async (values: any) => {
    try {
      if (editing) await updateUser(editing.id, { role: values.role, is_active: values.is_active })
      else await createUser(values)
      message.success('保存成功')
      setOpen(false)
      load()
    } catch (e: any) { message.error(e.response?.data?.detail || '保存失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '用户名', dataIndex: 'username' },
    { title: '角色', dataIndex: 'role', render: (v: string) => <Tag color={v === 'admin' ? 'red' : v === 'developer' ? 'blue' : 'default'}>{v}</Tag> },
    { title: '状态', dataIndex: 'is_active', render: (v: boolean) => v ? '启用' : '停用' },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue({ role: r.role, is_active: r.is_active }); setOpen(true) }}>编辑</Button>
        <Popconfirm title="确定删除？" onConfirm={async () => { await deleteUser(r.id); load() }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增用户</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>
      <Modal title={editing ? '编辑用户' : '新增用户'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ role: 'caller', is_active: true }}>
          {!editing && <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>}
          {!editing && <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password /></Form.Item>}
          <Form.Item name="role" label="角色"><Select options={[{ value: 'admin', label: '管理员' }, { value: 'developer', label: '开发者' }, { value: 'caller', label: '调用者' }]} /></Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
