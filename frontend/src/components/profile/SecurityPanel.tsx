import { useState } from 'react'
import { Button, Card, Form, Popconfirm, Space, Typography, message } from 'antd'
import PasswordFields, { type PasswordValues } from '../common/PasswordFields'
import TimeCell from '../common/TimeCell'
import { errorText } from '../../utils/errors'

// 个人中心"修改密码"与"退出其他设备"（docs/15 OP-03）。两者成功后服务端都让旧令牌失效并返回新令牌，
// 页面换上新令牌，当前页面不掉线、其他设备下一个请求回到登录页。请求由页面注入。
interface Props {
  passwordChangedAt: string | null
  onChangePassword: (oldPassword: string, newPassword: string) => Promise<void>
  onLogoutOthers: () => Promise<void>
}

export default function SecurityPanel({ passwordChangedAt, onChangePassword, onLogoutOthers }: Props) {
  const [form] = Form.useForm<PasswordValues>()
  const [submitting, setSubmitting] = useState(false)
  const submit = async (v: PasswordValues) => {
    setSubmitting(true)
    try {
      await onChangePassword(v.old_password, v.new_password)
      form.resetFields()
      message.success('密码已修改，其他设备上的登录已失效')
    } catch (e) { message.error(errorText(e, '修改失败')) } finally { setSubmitting(false) }
  }
  const logoutOthers = async () => {
    try { await onLogoutOthers(); message.success('其他设备上的登录已失效') } catch (e) { message.error(errorText(e, '操作失败')) }
  }

  return (
    <Space direction="vertical" size={12} style={{ width: '100%', maxWidth: 520 }}>
      <Card size="small" title="修改密码" extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>上次修改：<TimeCell value={passwordChangedAt} /></Typography.Text>}>
        <Form form={form} layout="vertical" onFinish={submit}>
          <PasswordFields />
          <Button type="primary" htmlType="submit" loading={submitting}>修改密码</Button>
        </Form>
      </Card>
      <Card size="small" title="退出其他设备">
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>
          在别的电脑或浏览器上登录过、又不确定是否已退出时用：除当前页面外，你的所有登录立即失效（API Key 不受影响）。
        </Typography.Paragraph>
        <Popconfirm title="退出其他设备？" description="其他电脑与浏览器上的登录会立即失效" onConfirm={logoutOthers}>
          <Button danger>退出其他设备</Button>
        </Popconfirm>
      </Card>
    </Space>
  )
}
