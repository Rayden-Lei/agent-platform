import { useState } from 'react'
import { toast } from 'sonner'
import { Bot, BookOpen, Eye, EyeOff, Lock, Sparkles, User, Workflow, Zap } from 'lucide-react'
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
//
// 版式：桌面左右分栏 —— 左边是品牌面（卖点 + 能力清单），右边是登录卡；窄屏收成单列，品牌面压到顶部当页头。
// 背景、卡片、文字全部走主题令牌，8 套配色与明暗主题切换时登录页跟着变（不再是写死的深灰底）。
const LOGIN_HINT = import.meta.env.VITE_LOGIN_HINT

const FEATURES = [
  { icon: Bot, title: '智能体编排', desc: '提示词、模型、工具与知识库的组合，发布后随时回滚' },
  { icon: Workflow, title: '可视化工作流', desc: '拖拽节点连成流程，定时任务与运行记录一并管理' },
  { icon: BookOpen, title: '知识库检索', desc: '文档切分、向量检索与引用溯源，答案有据可查' },
]

export default function Login() {
  const [loading, setLoading] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
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
      // 只在卡片内显示，不再同时弹 toast：两处重复报同一个错，还挡住页面顶部
      setError(errorText(err, '登录失败'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="page-blobs" />
      <div className="page-dots" />

      <div className="relative z-[1] my-auto grid w-full max-w-[980px] items-stretch gap-8 lg:grid-cols-[1.05fr_minmax(360px,420px)]">
        {/* ===== 品牌面（窄屏只在顶部显示标题） ===== */}
        <section className="hidden flex-col justify-center px-2 lg:flex">
          <div className="mb-8 flex items-center gap-3">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-[var(--radius)] shadow-[var(--shadow)]"
              style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}>
              <Bot className="size-[26px]" />
            </div>
            <div>
              <div className="text-[17px] font-semibold leading-tight text-foreground">智枢 · 智能体中台</div>
              <div className="mt-0.5 text-[12.5px] leading-tight text-muted-foreground">Agent Platform</div>
            </div>
          </div>

          <h2 className="m-0 text-[30px] font-semibold leading-[1.28] tracking-tight text-foreground">
            把智能体、工作流与知识库
            <br />
            收在<span style={{ color: 'var(--accent)' }}>一处管理</span>
          </h2>
          <p className="mb-0 mt-3.5 max-w-[420px] text-[14px] leading-relaxed text-muted-foreground">
            装配、调试、发布、观测走同一条链路；草稿与线上分离，每次发布都是一个可回滚的版本。
          </p>

          <ul className="m-0 mt-9 flex list-none flex-col gap-4 p-0">
            {FEATURES.map((f) => (
              <li key={f.title} className="flex items-start gap-3">
                <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg"
                  style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
                  <f.icon className="size-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-[13.5px] font-medium leading-snug text-foreground">{f.title}</span>
                  <span className="mt-0.5 block text-[12.5px] leading-relaxed text-muted-foreground">{f.desc}</span>
                </span>
              </li>
            ))}
          </ul>

          <div className="mt-9 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-muted-foreground">
            <span className="inline-flex items-center gap-1.5"><Zap className="size-3.5" style={{ color: 'var(--accent)' }} />流式对话</span>
            <span className="inline-flex items-center gap-1.5"><Sparkles className="size-3.5" style={{ color: 'var(--accent)' }} />8 套配色</span>
            <span className="inline-flex items-center gap-1.5"><Lock className="size-3.5" style={{ color: 'var(--accent)' }} />按角色授权</span>
          </div>
        </section>

        {/* ===== 登录卡 ===== */}
        <section className="flex flex-col justify-center">
          <div className="rounded-[var(--radius-lg)] border border-border bg-card p-7 shadow-[var(--shadow)] max-sm:p-6">
            {/* 窄屏没有品牌面，标题在这里补一份 */}
            <div className="mb-6 flex items-center gap-3 lg:hidden">
              <div className="flex size-11 shrink-0 items-center justify-center rounded-[var(--radius)]"
                style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}>
                <Bot className="size-6" />
              </div>
              <div className="min-w-0">
                <h1 className="m-0 truncate text-[18px] font-semibold leading-tight text-foreground">智枢 · 智能体中台</h1>
                <p className="m-0 mt-0.5 text-[12px] leading-tight text-muted-foreground">统一管理智能体、工作流与知识库</p>
              </div>
            </div>

            <div className="mb-6 hidden lg:block">
              <h1 className="m-0 text-[20px] font-semibold leading-tight text-foreground">登录</h1>
              <p className="m-0 mt-1.5 text-[13px] leading-relaxed text-muted-foreground">使用平台账号进入控制台</p>
            </div>

            {notice && (
              <div className="mb-5 rounded-lg px-3 py-2.5 text-[12.5px] leading-relaxed"
                style={{ background: 'var(--warning-soft)', border: '1px solid color-mix(in srgb, var(--warning) 32%, transparent)', color: 'var(--fg)' }}>
                {notice}
              </div>
            )}

            <form onSubmit={onFinish} className="flex flex-col gap-4" noValidate>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="login-username" className="text-[13px]">用户名</Label>
                <div className="relative">
                  <User className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="login-username"
                    autoComplete="username"
                    placeholder="请输入用户名"
                    value={username}
                    autoFocus
                    onChange={(e) => { setUsername(e.target.value); setError(null) }}
                    className="h-10 pl-9 text-[14px]"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <Label htmlFor="login-password" className="text-[13px]">密码</Label>
                <div className="relative">
                  <Lock className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    id="login-password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="current-password"
                    placeholder="请输入密码"
                    value={password}
                    onChange={(e) => { setPassword(e.target.value); setError(null) }}
                    className="h-10 pl-9 pr-10 text-[14px]"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? '隐藏密码' : '显示密码'}
                    aria-pressed={showPassword}
                    className="absolute right-1.5 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
                  >
                    {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                  </button>
                </div>
              </div>

              {/* 错误用软底提示，不挤在输入框和按钮之间把布局顶开 */}
              {error && (
                <div role="alert" className="rounded-lg px-3 py-2 text-[12.5px] leading-relaxed"
                  style={{ background: 'var(--danger-soft)', border: '1px solid color-mix(in srgb, var(--danger) 32%, transparent)', color: 'var(--danger)' }}>
                  {error}
                </div>
              )}

              <Button type="submit" disabled={loading} className="mt-1 h-10 w-full text-[14px]">
                {loading ? '登录中…' : '登录'}
              </Button>
            </form>

          </div>

          {LOGIN_HINT && (
            <p className="mb-0 mt-5 text-center text-[12px] leading-relaxed text-muted-foreground">
              {LOGIN_HINT}
            </p>
          )}
        </section>
      </div>
    </div>
  )
}
