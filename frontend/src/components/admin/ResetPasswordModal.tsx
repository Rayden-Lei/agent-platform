import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { resetUserPassword, type UserRow } from '../../api'
import { errorText } from '../../utils/errors'

// 管理员重置用户密码：两次输入一致且至少 6 位；服务端记审计（reset_password），不回显旧密码。
// 重置后该用户已登录的会话全部失效（token_version +1）；默认要求其下次登录先改密（docs/15 OP-04）
// onSaved：重置成功后由页面刷新列表，否则"待改密"标签要手动刷新才出现
interface Props { user: UserRow | null; onClose: () => void; onSaved: () => void }

export default function ResetPasswordModal({ user, onClose, onSaved }: Props) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [mustChange, setMustChange] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 换一个用户就清空输入：否则上一个用户输了一半的密码会残留到下一个
  useEffect(() => {
    if (!user) return
    setPassword(''); setConfirm(''); setMustChange(true); setError(null)
  }, [user])

  const onSubmit = async () => {
    if (!user) return
    // 服务端同样会校验，这里只是提前给出可读提示
    if (!password) { setError('请填写新密码'); return }
    if (password.length < 6) { setError('至少 6 位'); return }
    if (confirm !== password) { setError('两次输入不一致'); return }
    setSubmitting(true)
    try {
      await resetUserPassword(user.id, password, mustChange)
      toast.success(mustChange ? '密码已重置，该用户已登录的会话已失效，下次登录需先改密' : '密码已重置，该用户已登录的会话已失效')
      onSaved()
      onClose()
    } catch (e) { toast.error(errorText(e, '重置失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal
      open={!!user}
      size="sm"
      title={user ? `重置密码：${user.username}` : ''}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '重置中…' : '确定'}</Button>
        </>
      }
    >
      {/* 回车提交：和原来 antd Form 的手感保持一致 */}
      <form className="flex flex-col gap-3.5" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="reset-password">新密码</Label>
          <Input id="reset-password" type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="reset-confirm">确认新密码</Label>
          <Input id="reset-confirm" type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        </div>

        <div className="flex items-center gap-2">
          <Checkbox id="reset-must-change" checked={mustChange} onCheckedChange={(v) => setMustChange(v === true)} />
          <Label htmlFor="reset-must-change" className="cursor-pointer text-[13px] font-normal">要求该用户下次登录先修改密码</Label>
        </div>

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </form>
    </Modal>
  )
}
