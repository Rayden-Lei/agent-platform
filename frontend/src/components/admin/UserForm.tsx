import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { createUser, updateUser, type UserRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'

// 用户新增 / 改角色弹窗：编辑模式只改角色（启停在列表开关、密码走重置），不提供改用户名入口。
// 只有 3 个字段，用弹窗即可；而且它是从用户详情抽屉里点「改角色」打开的，抽屉里不再叠抽屉（DEVELOPMENT_RULES 第 6 条）。
interface Props { open: boolean; editing: UserRow | null; meId?: number; onClose: () => void; onSaved: () => void }
interface FormValues { username: string; password: string; role: string }

const EMPTY: FormValues = { username: '', password: '', role: 'caller' }

export default function UserForm({ open, editing, meId, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const roles = statusOptions('role')

  useEffect(() => {
    if (!open) return
    setError(null)
    setValues(editing ? { ...EMPTY, role: editing.role } : EMPTY)
  }, [open, editing])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  const onSubmit = async () => {
    // 服务端同样会校验，这里只是提前给出可读提示
    if (!editing) {
      const username = values.username.trim()
      if (!username) { setError('请输入用户名'); return }
      if (username.length < 2 || username.length > 64) { setError('用户名 2-64 位'); return }
      if (!values.password) { setError('请输入初始密码'); return }
      if (values.password.length < 6) { setError('初始密码至少 6 位'); return }
    }
    setSubmitting(true)
    try {
      if (editing) await updateUser(editing.id, { role: values.role })
      else await createUser({ username: values.username.trim(), password: values.password, role: values.role })
      toast.success('保存成功')
      onSaved()
      onClose()
    } catch (e) { toast.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal
      open={open}
      title={editing ? `修改角色：${editing.username}` : '新增用户'}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <form className="flex flex-col gap-3.5" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
        {!editing && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-username">用户名</Label>
            <Input id="user-username" autoComplete="off" value={values.username} maxLength={64} onChange={(e) => set('username', e.target.value)} />
          </div>
        )}

        {!editing && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-password">初始密码</Label>
            <Input id="user-password" type="password" autoComplete="new-password" value={values.password} onChange={(e) => set('password', e.target.value)} />
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="user-role">角色</Label>
          <Select value={values.role} onValueChange={(v) => set('role', v)}>
            <SelectTrigger id="user-role" className="w-full">
              <SelectValue placeholder="选择角色" />
            </SelectTrigger>
            <SelectContent>
              {roles.map((r) => <SelectItem key={r.value} value={r.value}>{r.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <p className="m-0 text-[12px] text-muted-foreground">
            {editing && editing.id === meId ? '不能降低自己的角色' : '管理员：全部；开发者：资源管理与运行；调用者：仅对话与自己的会话'}
          </p>
        </div>

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </form>
    </Modal>
  )
}
