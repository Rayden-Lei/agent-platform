import { useState } from 'react'
import { toast } from 'sonner'
import { Bot, Lock, User } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { login } from '../api'
import { useAuth } from '../store/auth'
import { Button } from '@/components/shadcn/button'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { errorText } from '../utils/errors'
import { safeRedirect, takeLoginNotice } from '../utils/redirect'

// 登录页：提交用户名 / 密码到 /auth/login，成功后把 token 与用户信息写入全局 auth store
// （store 内部会持久化到 localStorage），再回到 redirect 指向的站内页面（没有或不安全时回首页，docs/15 OP-02）；失败统一提示后端 detail。
// 被踢回来时（令牌失效、账号停用）显示一次原因。页脚提示文案来自构建时的 VITE_LOGIN_HINT（不配置就不显示）。
const LOGIN_HINT = import.meta.env.VITE_LOGIN_HINT

export default function Login() {
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [notice] = useState(takeLoginNotice) // 只在首次渲染取一次，刷新登录页后不再显示
  const { setAuth } = useAuth()

  const onFinish = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username) { setError('请输入用户名'); return }
    if (!password) { setError('请输入密码'); return }
    setLoading(true)
    setError(null)
    try {
      const res = await login({ username, password })
      // setAuth 写入全局登录态；token 同时由 client 拦截器从 localStorage 读取注入请求头
      setAuth(res.token, res.user)
      toast.success('登录成功')
      navigate(safeRedirect(params.get('redirect')), { replace: true })
    } catch (err) {
      const text = errorText(err, '登录失败')
      setError(text)
      toast.error(text)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-card-header">
          <div className="mb-2 flex justify-center"><Bot className="size-9" /></div>
          <div className="text-[22px] font-semibold">智枢·智能体平台</div>
          <div className="mt-1.5 text-[13px] opacity-85">统一管理智能体、工作流与知识库</div>
        </div>
        <div className="p-7">
          {notice && (
            <div className="mb-4 rounded-lg border border-[rgba(217,119,6,.35)] bg-[rgba(217,119,6,.10)] px-3 py-2 text-[12.5px]">{notice}</div>
          )}
          <form onSubmit={onFinish} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-username">用户名</Label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="login-username"
                  autoComplete="username"
                  placeholder="用户名"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="h-10 pl-9 text-[14px]"
                />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="login-password">密码</Label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  placeholder="密码"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="h-10 pl-9 text-[14px]"
                />
              </div>
            </div>
            {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
            <Button type="submit" disabled={loading} className="h-10 w-full text-[14px]">
              {loading ? '登录中…' : '登录'}
            </Button>
            {LOGIN_HINT && <div className="text-center text-[12px] text-muted-foreground">{LOGIN_HINT}</div>}
          </form>
        </div>
      </div>
    </div>
  )
}
