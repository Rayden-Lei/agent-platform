import { useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, Switch } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listUsers, createUser, updateUser, deleteUser } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// 用户管理页：账号的增删改与角色分配（admin/developer/caller）。
// 注意：编辑模式只允许改角色与启用状态，不提供修改用户名/密码的入口（新增时才填写）。
export default function Users() {
  const { tableProps, reload } = usePagedList(listUsers)
  const [open, setOpen] = useState(false)
  // editing 非空表示当前弹窗处于编辑模式（提交时走 update），否则为新增（走 create）
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  // 新增/编辑共用提交：编辑时只提交角色与启用状态（不回传用户名/密码），否则走创建
  const onSubmit = async (values: any) => {
    try {
      if (editing) await updateUser(editing.id, { role: values.role, is_active: values.is_active })
      else await createUser(values)
      message.success('保存成功')
      setOpen(false)
      reload()
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
        <Popconfirm title="确定删除？" onConfirm={async () => { try { await deleteUser(r.id); reload() } catch (e: any) { message.error(e.response?.data?.detail || '删除失败') } }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>用户管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增用户</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>
      <Modal title={editing ? '编辑用户' : '新增用户'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ role: 'caller', is_active: true }}>
          {/* 仅新增模式显示用户名/密码输入；编辑模式不提供，避免误改登录凭据 */}
          {!editing && <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>}
          {!editing && <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password /></Form.Item>}
          <Form.Item name="role" label="角色"><Select options={[{ value: 'admin', label: '管理员' }, { value: 'developer', label: '开发者' }, { value: 'caller', label: '调用者' }]} /></Form.Item>
          <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
