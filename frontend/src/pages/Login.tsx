import { useState } from 'react'
import { Alert, Form, Input, Button, message } from 'antd'
import { UserOutlined, LockOutlined, RobotOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { login } from '../api'
import { useAuth } from '../store/auth'
import { errorText } from '../utils/errors'
import { safeRedirect, takeLoginNotice } from '../utils/redirect'

// 登录页：提交用户名 / 密码到 /auth/login，成功后把 token 与用户信息写入全局 auth store
// （store 内部会持久化到 localStorage），再回到 redirect 指向的站内页面（没有或不安全时回首页，docs/15 OP-02）；失败统一提示后端 detail。
// 被踢回来时（令牌失效、账号停用）显示一次原因。页脚提示文案来自构建时的 VITE_LOGIN_HINT（不配置就不显示）。
const LOGIN_HINT = import.meta.env.VITE_LOGIN_HINT

export default function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [notice] = useState(takeLoginNotice) // 只在首次渲染取一次，刷新登录页后不再显示
  const { setAuth } = useAuth()

  const onFinish = async (values: { username: string; password: string }) => {
    setLoading(true)
    try {
      const res = await login(values)
      // setAuth 写入全局登录态；token 同时由 client 拦截器从 localStorage 读取注入请求头
      setAuth(res.token, res.user)
      message.success('登录成功')
      navigate(safeRedirect(params.get('redirect')), { replace: true })
    } catch (e) {
      message.error(errorText(e, '登录失败'))
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
          {notice && <Alert type="warning" showIcon style={{ marginBottom: 16 }} message={notice} />}
          <Form onFinish={onFinish} size="large">
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }]}>
              <Input prefix={<UserOutlined style={{ color: '#aaa' }} />} placeholder="用户名" autoComplete="username" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined style={{ color: '#aaa' }} />} placeholder="密码" autoComplete="current-password" />
            </Form.Item>
            <Form.Item style={{ marginBottom: 8 }}>
              <Button type="primary" htmlType="submit" block loading={loading} size="large">登录</Button>
            </Form.Item>
            {LOGIN_HINT && <div style={{ textAlign: 'center', fontSize: 12, color: '#999' }}>{LOGIN_HINT}</div>}
          </Form>
        </div>
      </div>
    </div>
  )
}
