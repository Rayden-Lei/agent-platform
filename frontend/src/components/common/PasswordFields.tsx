import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'

// 改密表单的三个字段（当前密码 / 新密码 / 确认）：强制改密弹窗用。
// 规则与后端 ChangePasswordIn 一致（6～128 位、不能与当前密码相同）；受控组件，校验由调用方在提交前做。
export interface PasswordValues { old_password: string; new_password: string; confirm: string }

interface Props {
  value: PasswordValues
  onChange: (patch: Partial<PasswordValues>) => void
}

export default function PasswordFields({ value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="pwd-old">当前密码</Label>
        <Input id="pwd-old" type="password" autoComplete="current-password" value={value.old_password} onChange={(e) => onChange({ old_password: e.target.value })} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="pwd-new">新密码</Label>
        <Input id="pwd-new" type="password" autoComplete="new-password" value={value.new_password} onChange={(e) => onChange({ new_password: e.target.value })} />
        <p className="m-0 text-[12px] text-muted-foreground">6～128 位，不能与当前密码相同</p>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="pwd-confirm">确认新密码</Label>
        <Input id="pwd-confirm" type="password" autoComplete="new-password" value={value.confirm} onChange={(e) => onChange({ confirm: e.target.value })} />
      </div>
    </div>
  )
}
