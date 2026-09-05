import { useEffect, useState } from 'react'
import { Form, Input, Modal, message } from 'antd'
import { resetUserPassword, type UserRow } from '../../api'
import { errorText } from '../../utils/errors'

// 管理员重置用户密码：两次输入一致且至少 6 位；服务端记审计（reset_password），不回显旧密码。
interface Props { user: UserRow | null; onClose: () => void }

export default function ResetPasswordModal({ user, onClose }: Props) {
  const [form] = Form.useForm<{ password: string; confirm: string }>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (user) form.resetFields() }, [user, form])
  const onSubmit = async (values: { password: string; confirm: string }) => {
    if (!user) return
    setSubmitting(true)
    try { await resetUserPassword(user.id, values.password); message.success('密码已重置，请线下告知该用户'); onClose() } catch (e) { message.error(errorText(e, '重置失败')) } finally { setSubmitting(false) }
  }
  return (
    <Modal title={user ? `重置密码：${user.username}` : ''} open={!!user} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item name="password" label="新密码" rules={[{ required: true }, { min: 6, message: '至少 6 位' }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="confirm" label="确认新密码" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator: (_, v) => (v === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致'))) })]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
      </Form>
    </Modal>
  )
}
