import { useEffect, useState } from 'react'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import type { MeInfo, ProfileInput } from '../../api'

// 个人中心"基本资料"（docs/15 OP-03）：显示名、邮箱、手机号。用户名与角色只有管理员能改，这里只读。
// 手机号接口只给脱敏值：输入框留空表示不改，"清除"单独一个按钮；保存由页面注入。
interface Props {
  me: MeInfo
  saving: boolean
  onSave: (input: ProfileInput) => Promise<boolean>
}
interface Values { display_name: string; email: string; phone: string }

const PHONE_PATTERN = /^\+?[0-9][0-9-]{4,19}$/
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function ProfileForm({ me, saving, onSave }: Props) {
  const [values, setValues] = useState<Values>({ display_name: '', email: '', phone: '' })
  const [error, setError] = useState<string | null>(null)

  // 页面重新取回资料（或切换用户）时同步输入框；手机号永远从空开始，留空即不改
  useEffect(() => {
    setError(null)
    setValues({ display_name: me.display_name ?? '', email: me.email ?? '', phone: '' })
  }, [me])

  const set = (key: keyof Values, v: string) => setValues((s) => ({ ...s, [key]: v }))

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const displayName = values.display_name.trim()
    const email = values.email.trim()
    const phone = values.phone.trim()
    // 服务端同样会校验，这里只是提前给出可读提示
    if (displayName.length > 64) { setError('显示名最多 64 个字符'); return }
    if (email && !EMAIL_PATTERN.test(email)) { setError('邮箱格式不正确'); return }
    if (email.length > 128) { setError('邮箱最多 128 个字符'); return }
    if (phone && !PHONE_PATTERN.test(phone)) { setError('5～20 位数字，可带 + 与 -'); return }
    const input: ProfileInput = { display_name: displayName || null, email: email || null }
    if (phone) input.phone = phone
    if (await onSave(input)) setValues((s) => ({ ...s, phone: '' }))
  }

  return (
    <form className="flex max-w-[420px] flex-col gap-3.5" onSubmit={submit}>
      <div className="flex flex-col gap-1.5">
        <Label>用户名</Label>
        <p className="m-0 text-[13px] leading-9 text-foreground">{me.username}</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="profile-display-name">显示名</Label>
        <Input id="profile-display-name" value={values.display_name} maxLength={64} placeholder="不填则显示用户名" onChange={(e) => set('display_name', e.target.value)} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="profile-email">邮箱</Label>
        <Input id="profile-email" type="email" value={values.email} maxLength={128} placeholder="name@example.com" onChange={(e) => set('email', e.target.value)} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="profile-phone">手机号</Label>
        <div className="flex items-center gap-2">
          <Input
            id="profile-phone"
            inputMode="tel"
            value={values.phone}
            placeholder={me.phone_masked ? '输入新号码以修改' : '输入手机号'}
            onChange={(e) => set('phone', e.target.value)}
          />
          {/* 清除是破坏性操作：先点一次变"确认?"，3 秒内不再点就复原 */}
          {me.phone_masked && (
            <InlineConfirm message="清除手机号？" confirmLabel="清除" onConfirm={() => { void onSave({ phone: null }) }}>
              <Button size="md">清除</Button>
            </InlineConfirm>
          )}
        </div>
        <p className="m-0 text-[12px] text-muted-foreground">{me.phone_masked ? `当前：${me.phone_masked}（留空不改）` : '未设置'}</p>
      </div>

      {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}

      <div>
        <Button variant="primary" size="md" type="submit" disabled={saving}>{saving ? '保存中…' : '保存'}</Button>
      </div>
    </form>
  )
}
