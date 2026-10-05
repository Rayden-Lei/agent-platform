import { useEffect, useState } from 'react'
import { Checkbox, Form, Input, Modal, message } from 'antd'
import { resetUserPassword, type UserRow } from '../../api'
import { errorText } from '../../utils/errors'

// 管理员重置用户密码：两次输入一致且至少 6 位；服务端记审计（reset_password），不回显旧密码。
// 重置后该用户已登录的会话全部失效（token_version +1）；默认要求其下次登录先改密（docs/15 OP-04）
// onSaved：重置成功后由页面刷新列表，否则"待改密"标签要手动刷新才出现
interface Props { user: UserRow | null; onClose: () => void; onSaved: () => void }
interface FormValues { password: string; confirm: string; mustChange: boolean }

export default function ResetPasswordModal({ user, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => { if (user) form.resetFields() }, [user, form])
  const onSubmit = async (values: FormValues) => {
    if (!user) return
    setSubmitting(true)
    try {
      await resetUserPassword(user.id, values.password, values.mustChange)
      message.success(values.mustChange ? '密码已重置，该用户已登录的会话已失效，下次登录需先改密' : '密码已重置，该用户已登录的会话已失效')
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, '重置失败')) } finally { setSubmitting(false) }
  }
  return (
    <Modal title={user ? `重置密码：${user.username}` : ''} open={!!user} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ mustChange: true }}>
        <Form.Item name="password" label="新密码" rules={[{ required: true }, { min: 6, message: '至少 6 位' }]}><Input.Password autoComplete="new-password" /></Form.Item>
        <Form.Item name="confirm" label="确认新密码" dependencies={['password']} rules={[{ required: true }, ({ getFieldValue }) => ({ validator: (_, v) => (v === getFieldValue('password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致'))) })]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="mustChange" valuePropName="checked"><Checkbox>要求该用户下次登录先修改密码</Checkbox></Form.Item>
      </Form>
    </Modal>
  )
}
