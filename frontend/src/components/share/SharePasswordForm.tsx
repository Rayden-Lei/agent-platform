import { Alert, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined } from '@ant-design/icons'

// 分享链接设了访问密码时的输入页。提交由页面注入；密码错误的提示由页面传回（后端 401「访问密码错误」，每分钟最多尝试 5 次）。
interface Props {
  agentName?: string
  error?: string | null
  submitting: boolean
  onSubmit: (password: string) => void
}

export default function SharePasswordForm({ agentName, error, submitting, onSubmit }: Props) {
  return (
    <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
      <Card style={{ width: '100%', maxWidth: 360 }}>
        <Typography.Title level={5} style={{ marginTop: 0 }}><LockOutlined /> {agentName ? `「${agentName}」需要访问密码` : '需要访问密码'}</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ fontSize: 13 }}>请输入分享者提供的访问密码</Typography.Paragraph>
        {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
        <Form layout="vertical" onFinish={(v: { password: string }) => onSubmit(v.password)}>
          <Form.Item name="password" rules={[{ required: true, message: '请输入访问密码' }]}>
            <Input.Password autoFocus autoComplete="off" placeholder="访问密码" maxLength={64} />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={submitting}>进入</Button>
        </Form>
      </Card>
    </div>
  )
}
