import { useState } from 'react'
import { Lock } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/shadcn/alert'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Button from '../ui/Button'

// 分享链接设了访问密码时的输入页。提交由页面注入；密码错误的提示由页面传回（后端 401「访问密码错误」，每分钟最多尝试 5 次）。
// 访客不需要登录：这里只有密码一个字段。
interface Props {
  agentName?: string
  error?: string | null
  submitting: boolean
  onSubmit: (password: string) => void
}

export default function SharePasswordForm({ agentName, error, submitting, onSubmit }: Props) {
  const [password, setPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!password.trim()) { setLocalError('请输入访问密码'); return }
    setLocalError(null)
    onSubmit(password)
  }

  return (
    <div className="flex h-full items-center justify-center p-4">
      <div className="w-full max-w-[360px] rounded-xl border border-border bg-card p-5">
        <h2 className="m-0 flex items-center gap-1.5 text-[14px] font-semibold text-foreground">
          <Lock className="size-4 text-muted-foreground" aria-hidden="true" />
          {agentName ? `「${agentName}」需要访问密码` : '需要访问密码'}
        </h2>
        <p className="mb-3 mt-1.5 text-[12.5px] leading-relaxed text-muted-foreground">请输入分享者提供的访问密码</p>

        {error && (
          <Alert variant="destructive" className="mb-3">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <form className="flex flex-col gap-3" onSubmit={submit}>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="share-password" className="sr-only">访问密码</Label>
            <Input
              id="share-password"
              type="password"
              autoFocus
              autoComplete="off"
              placeholder="访问密码"
              maxLength={64}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {localError && <p className="m-0 text-[12.5px] text-destructive">{localError}</p>}
          </div>
          <Button variant="primary" size="md" type="submit" block disabled={submitting}>{submitting ? '验证中…' : '进入'}</Button>
        </form>
      </div>
    </div>
  )
}
