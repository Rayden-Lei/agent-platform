import { useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import TimeCell from '../common/TimeCell'
import { errorText } from '../../utils/errors'

// 个人中心"修改密码"与"退出其他设备"（docs/15 OP-03）。两者成功后服务端都让旧令牌失效并返回新令牌，
// 页面换上新令牌，当前页面不掉线、其他设备下一个请求回到登录页。请求由页面注入。
// 改密的三个字段与后端 ChangePasswordIn 一致（6～128 位、不能与当前密码相同）；不再复用 antd 版 PasswordFields。
interface Props {
  passwordChangedAt: string | null
  onChangePassword: (oldPassword: string, newPassword: string) => Promise<void>
  onLogoutOthers: () => Promise<void>
}

export default function SecurityPanel({ passwordChangedAt, onChangePassword, onLogoutOthers }: Props) {
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    // 服务端同样会校验，这里只是提前给出可读提示
    if (!oldPassword) { setError('请填写当前密码'); return }
    if (newPassword.length < 6 || newPassword.length > 128) { setError('6～128 位'); return }
    if (newPassword === oldPassword) { setError('不能与当前密码相同'); return }
    if (confirm !== newPassword) { setError('两次输入不一致'); return }
    setSubmitting(true)
    try {
      await onChangePassword(oldPassword, newPassword)
      setOldPassword(''); setNewPassword(''); setConfirm(''); setError(null)
      toast.success('密码已修改，其他设备上的登录已失效')
    } catch (e) { setError(errorText(e, '修改失败')) } finally { setSubmitting(false) }
  }

  const logoutOthers = async () => {
    try { await onLogoutOthers(); toast.success('其他设备上的登录已失效') } catch (e) { toast.error(errorText(e, '操作失败')) }
  }

  return (
    <div className="flex w-full max-w-[520px] flex-col gap-3">
      <section className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex items-start justify-between gap-3">
          <h3 className="m-0 text-[13px] font-semibold text-foreground">修改密码</h3>
          <span className="text-[12px] text-muted-foreground">上次修改：<TimeCell value={passwordChangedAt} /></span>
        </div>

        <form className="flex flex-col gap-3.5" onSubmit={submit}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="security-old">当前密码</Label>
            <Input id="security-old" type="password" autoComplete="current-password" value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="security-new">新密码</Label>
            <Input id="security-new" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="security-confirm">确认新密码</Label>
            <Input id="security-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          </div>

          {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}

          <div>
            <Button variant="primary" size="md" type="submit" disabled={submitting}>{submitting ? '提交中…' : '修改密码'}</Button>
          </div>
        </form>
      </section>

      <section className="rounded-xl border border-border bg-card p-4">
        <h3 className="m-0 mb-3 text-[13px] font-semibold text-foreground">退出其他设备</h3>
        <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
          在别的电脑或浏览器上登录过、又不确定是否已退出时用：除当前页面外，你的所有登录立即失效（API Key 不受影响）。
        </p>
        <div className="mt-3">
          <InlineConfirm message="其他电脑与浏览器上的登录会立即失效" confirmLabel="退出其他设备" danger onConfirm={() => { void logoutOthers() }}>
            <Button variant="danger" size="md">退出其他设备</Button>
          </InlineConfirm>
        </div>
      </section>
    </div>
  )
}
