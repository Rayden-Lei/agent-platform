import { useState } from 'react'
import { toast } from 'sonner'
import { TriangleAlert } from 'lucide-react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import PasswordFields, { type PasswordValues } from '../common/PasswordFields'
import { errorText } from '../../utils/errors'

// 必须改密（docs/15 OP-04）：服务端对这个账号除改密与 /auth/me 外一律 403「请先修改初始密码」，这里是唯一出路。
// 不可关闭，只能改密或退出登录；改密请求由布局层注入（组件不发请求）。
interface Props {
  open: boolean
  username?: string
  onSubmit: (oldPassword: string, newPassword: string) => Promise<void>
  onLogout: () => void
}

const EMPTY: PasswordValues = { old_password: '', new_password: '', confirm: '' }

export default function ForcePasswordModal({ open, username, onSubmit, onLogout }: Props) {
  const [values, setValues] = useState(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    // 规则与后端 ChangePasswordIn 一致（见 PasswordFields 注释）
    if (!values.old_password) { setError('请填写当前密码'); return }
    if (values.new_password.length < 6 || values.new_password.length > 128) { setError('新密码需要 6～128 位'); return }
    if (values.new_password === values.old_password) { setError('新密码不能与当前密码相同'); return }
    if (values.new_password !== values.confirm) { setError('两次输入不一致'); return }
    setSubmitting(true)
    setError(null)
    try {
      await onSubmit(values.old_password, values.new_password)
    } catch (e) {
      setError(errorText(e, '修改失败'))
      toast.error(errorText(e, '修改失败'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      size="sm"
      dismissible={false}
      title="请先修改密码"
      onClose={() => { /* 不可关闭：只能改密或退出登录 */ }}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onLogout}>退出登录</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={submit}>{submitting ? '提交中…' : '修改密码'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-start gap-2 rounded-lg border border-[rgba(217,119,6,.35)] bg-[rgba(217,119,6,.10)] px-3 py-2">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-[#B45309]" />
          <span className="text-[12.5px] leading-relaxed">
            账号 {username ?? ''} 在用初始密码或刚被管理员重置过，改密之前其他功能都不可用；改完后其他设备上的登录会失效。
          </span>
        </div>
        <form onSubmit={(e) => { e.preventDefault(); submit() }}>
          <PasswordFields value={values} onChange={(patch) => setValues((s) => ({ ...s, ...patch }))} />
          {error && <p className="m-0 mt-3 text-[12.5px] text-destructive">{error}</p>}
        </form>
      </div>
    </Modal>
  )
}
