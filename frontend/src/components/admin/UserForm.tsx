import { useEffect, useState } from 'react'
import { Form, Input, Modal, Select, message } from 'antd'
import { createUser, updateUser, type UserRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'

// 用户新增 / 改角色弹窗：编辑模式只改角色（启停在列表开关、密码走重置），不提供改用户名入口。
interface Props { open: boolean; editing: UserRow | null; meId?: number; onClose: () => void; onSaved: () => void }
interface FormValues { username: string; password: string; role: string }

export default function UserForm({ open, editing, meId, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (open) { form.resetFields(); if (editing) form.setFieldsValue({ role: editing.role }) } }, [open, editing, form])

  const onSubmit = async (values: FormValues) => {
    setSubmitting(true)
    try {
      if (editing) await updateUser(editing.id, { role: values.role })
      else await createUser({ username: values.username, password: values.password, role: values.role })
      message.success('保存成功')
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `修改角色：${editing.username}` : '新增用户'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ role: 'caller' }}>
        {!editing && <Form.Item name="username" label="用户名" rules={[{ required: true }, { min: 2, max: 64 }]}><Input autoComplete="off" /></Form.Item>}
        {!editing && <Form.Item name="password" label="初始密码" rules={[{ required: true }, { min: 6, message: '至少 6 位' }]}><Input.Password autoComplete="new-password" /></Form.Item>}
        <Form.Item name="role" label="角色" extra={editing && editing.id === meId ? '不能降低自己的角色' : '管理员：全部；开发者：资源管理与运行；调用者：仅对话与自己的会话'}>
          <Select options={statusOptions('role')} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
