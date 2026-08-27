import { useState } from 'react'
import { Form, Input, Button, message } from 'antd'
import { UserOutlined, LockOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { login } from '../api'
import { useAuth } from '../store/auth'

export default function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { setAuth } = useAuth()

  const onFinish = async (values: any) => {
    setLoading(true)
    try {
      const res: any = await login(values)
      setAuth(res.token, res.user)
      message.success('登录成功')
      navigate('/')
    } catch (e: any) {
      message.error(e.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card-header">
          <div style={{ fontSize: 36, marginBottom: 8 }}><RobotOutlined /></div>
          <div style={{ fontSize: 22, fontWeight: 600 }}>智枢·智能体平台</div>
          <div style={{ fontSize: 13, opacity: 0.85, marginTop: 6 }}>统一管理智能体、工作流与知识库</div>
        </div>
        <div style={{ padding: 28 }}>
          <Form onFinish={onFinish} size="large">
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input prefix={<UserOutlined style={{ color: '#aaa' }} />} placeholder="用户名" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined style={{ color: '#aaa' }} />} placeholder="密码" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 8 }}>
              <Button type="primary" htmlType="submit" block loading={loading} size="large">登录</Button>
            </Form.Item>
            <div style={{ textAlign: 'center', fontSize: 12, color: '#999' }}>默认账号 admin / admin123</div>
          </Form>
        </div>
      </div>
    </div>
  )
}
