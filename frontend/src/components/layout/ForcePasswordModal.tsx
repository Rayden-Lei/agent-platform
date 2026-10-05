import { useState } from 'react'
import { Alert, Button, Form, Modal, message } from 'antd'
import PasswordFields, { type PasswordValues } from '../common/PasswordFields'
import { errorText } from '../../utils/errors'

// 必须改密（docs/15 OP-04）：服务端对这个账号除改密与 /auth/me 外一律 403「请先修改初始密码」，这里是唯一出路。
// 不可关闭，只能改密或退出登录；改密请求由布局层注入（组件不发请求）。
interface Props {
  open: boolean
  username?: string
  onSubmit: (oldPassword: string, newPassword: string) => Promise<void>
  onLogout: () => void
}
export default function ForcePasswordModal({ open, username, onSubmit, onLogout }: Props) {
  const [form] = Form.useForm<PasswordValues>()
  const [submitting, setSubmitting] = useState(false)
  const submit = async (values: PasswordValues) => {
    setSubmitting(true)
    try { await onSubmit(values.old_password, values.new_password) } catch (e) { message.error(errorText(e, '修改失败')) } finally { setSubmitting(false) }
  }
  return (
    <Modal title="请先修改密码" open={open} closable={false} maskClosable={false} keyboard={false} destroyOnHidden
      footer={[<Button key="logout" onClick={onLogout}>退出登录</Button>, <Button key="ok" type="primary" loading={submitting} onClick={() => form.submit()}>修改密码</Button>]}>
      <Alert type="warning" showIcon style={{ marginBottom: 16 }}
        message={`账号 ${username ?? ''} 在用初始密码或刚被管理员重置过，改密之前其他功能都不可用；改完后其他设备上的登录会失效。`} />
      <Form form={form} layout="vertical" onFinish={submit}>
        <PasswordFields />
      </Form>
    </Modal>
  )
}
