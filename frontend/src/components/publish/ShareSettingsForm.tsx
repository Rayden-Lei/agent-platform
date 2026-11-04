import { useEffect, useState } from 'react'
import { CalendarDays } from 'lucide-react'
import dayjs from 'dayjs'
import { Calendar } from '@/components/shadcn/calendar'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Switch } from '@/components/shadcn/switch'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import type { AgentShare, AgentShareInput, ShareAccessMode } from '../../api'

// 分享链接的访问与限额设置（docs/15 3.6）：访问方式、访问密码、有效期、三个限额、访客能力。整体覆盖保存，开关状态沿用当前值。
// 本组件含三个内部小部件（互斥分段按钮 Segment、带单位数字 NumberField、HTTP 工具确认弹窗），超出行数约定属已知取舍。
// 密码三态：不设（有旧密码时清除）/ 保留现有 / 设置新密码；改密码或访问方式会让已打开页面的访客重新进入。数据与保存由页面注入。
type PasswordMode = 'none' | 'keep' | 'set'
interface Values {
  access_mode: ShareAccessMode
  password_mode: PasswordMode
  password: string
  expires_at: string | null // ISO 串；null 表示长期有效
  rate_limit_per_minute: number
  daily_message_limit: number
  visitor_daily_limit: number
  allow_http_tools: boolean
  show_citations: boolean
}
interface Props {
  share: AgentShare
  saving: boolean
  onSave: (input: AgentShareInput) => Promise<boolean>
}

const toValues = (s: AgentShare): Values => ({
  access_mode: s.access_mode, password_mode: s.password_set ? 'keep' : 'none', password: '',
  expires_at: s.expires_at, rate_limit_per_minute: s.rate_limit_per_minute, daily_message_limit: s.daily_message_limit,
  visitor_daily_limit: s.visitor_daily_limit, allow_http_tools: s.allow_http_tools, show_citations: s.show_citations,
})

// 互斥选项：原来 antd 的 Radio.Group，用语义 token 的分段按钮表达
function Segment<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex flex-wrap items-center gap-1 self-start rounded-lg border border-border p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={o.value === value}
          onClick={() => onChange(o.value)}
          className={o.value === value
            ? 'rounded-md bg-primary px-2.5 py-1 text-[12.5px] font-medium text-primary-foreground'
            : 'rounded-md px-2.5 py-1 text-[12.5px] text-muted-foreground hover:bg-accent hover:text-foreground'}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// 带单位的数字输入：原来 antd InputNumber 的 addonAfter
function NumberField({ id, label, unit, value, min, max, onChange }: { id: string; label: string; unit: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-1.5">
        <Input id={id} type="number" min={min} max={max} value={value} className="w-[110px]" onChange={(e) => onChange(Number(e.target.value))} />
        <span className="text-[12.5px] text-muted-foreground">{unit}</span>
      </div>
    </div>
  )
}

export default function ShareSettingsForm({ share, saving, onSave }: Props) {
  const [values, setValues] = useState<Values>(() => toValues(share))
  const [error, setError] = useState<string | null>(null)
  const [confirmTools, setConfirmTools] = useState(false)
  useEffect(() => { setValues(toValues(share)); setError(null) }, [share])

  const set = <K extends keyof Values>(key: K, v: Values[K]) => setValues((s) => ({ ...s, [key]: v }))
  const expires = values.expires_at ? dayjs(values.expires_at) : null

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    // 服务端同样会校验，这里只是提前给出可读提示
    if (values.password_mode === 'set') {
      if (!values.password.trim()) { setError('请输入访问密码'); return }
      if (values.password.length < 4 || values.password.length > 64) { setError('4～64 个字符'); return }
    }
    setError(null)
    const input: AgentShareInput = {
      is_enabled: share.is_enabled, access_mode: values.access_mode,
      expires_at: values.expires_at ? dayjs(values.expires_at).format() : null, // format() 是带偏移量的 ISO 8601
      rate_limit_per_minute: values.rate_limit_per_minute, daily_message_limit: values.daily_message_limit,
      visitor_daily_limit: values.visitor_daily_limit, allow_http_tools: values.allow_http_tools, show_citations: values.show_citations,
    }
    if (values.password_mode === 'set') input.password = values.password
    else if (values.password_mode === 'none' && share.password_set) input.password = null
    if (await onSave(input)) set('password', '')
  }

  return (
    <form className="flex max-w-[640px] flex-col gap-3.5" onSubmit={submit}>
      <div className="flex flex-col gap-1.5">
        <Label>访问方式</Label>
        <Segment
          value={values.access_mode}
          onChange={(v) => set('access_mode', v)}
          options={[{ value: 'public', label: '公开（拿到链接即可）' }, { value: 'login', label: '仅登录用户' }]}
        />
        <p className="m-0 text-[12px] text-muted-foreground">仅登录：访客用平台账号登录后访问，会话记在其本人名下，检索按其本人的角色</p>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>访问密码</Label>
        <Segment
          value={values.password_mode}
          onChange={(v) => set('password_mode', v)}
          options={[
            { value: 'none', label: '不设' },
            ...(share.password_set ? [{ value: 'keep' as PasswordMode, label: '保留现有密码' }] : []),
            { value: 'set', label: share.password_set ? '改成新密码' : '设置密码' },
          ]}
        />
      </div>

      {values.password_mode === 'set' && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="share-new-password" className="sr-only">访问密码</Label>
          <Input
            id="share-new-password"
            type="password"
            autoComplete="new-password"
            placeholder="4～64 个字符"
            className="max-w-[320px]"
            value={values.password}
            onChange={(e) => set('password', e.target.value)}
          />
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <Label>有效期至</Label>
        <div className="flex items-center gap-2">
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="flex h-9 items-center gap-1.5 rounded-lg border border-input bg-transparent px-3 text-[13px] text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              >
                <CalendarDays className="size-3.5 text-muted-foreground" aria-hidden="true" />
                {expires ? expires.format('YYYY-MM-DD HH:mm') : '长期有效'}
              </button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
              <Calendar
                mode="single"
                selected={expires?.toDate()}
                disabled={{ before: dayjs().startOf('day').toDate() }}
                onSelect={(d) => {
                  if (!d) return
                  const base = dayjs(d).hour(expires?.hour() ?? 0).minute(expires?.minute() ?? 0).second(0)
                  set('expires_at', base.format())
                }}
              />
              <div className="flex items-center gap-2 border-t border-border p-2">
                <Input
                  type="time"
                  aria-label="时间"
                  className="h-8 w-[110px] text-[12.5px]"
                  value={expires ? expires.format('HH:mm') : '00:00'}
                  onChange={(e) => {
                    const [h, m] = e.target.value.split(':').map(Number)
                    set('expires_at', dayjs(expires ?? undefined).hour(h || 0).minute(m || 0).second(0).format())
                  }}
                />
                {values.expires_at && (
                  <button type="button" className="text-[12.5px] text-muted-foreground hover:text-foreground" onClick={() => set('expires_at', null)}>清除</button>
                )}
              </div>
            </PopoverContent>
          </Popover>
        </div>
        <p className="m-0 text-[12px] text-muted-foreground">不填则长期有效；过期后访客打开看到「链接已过期」</p>
      </div>

      <div className="flex flex-wrap gap-4">
        <NumberField id="share-rate" label="整条链接每分钟" unit="次" min={1} max={600} value={values.rate_limit_per_minute} onChange={(v) => set('rate_limit_per_minute', v)} />
        <NumberField id="share-daily" label="整条链接每天" unit="条" min={1} max={100000} value={values.daily_message_limit} onChange={(v) => set('daily_message_limit', v)} />
        <NumberField id="share-visitor" label="每位访客每天" unit="条" min={1} max={1000} value={values.visitor_daily_limit} onChange={(v) => set('visitor_daily_limit', v)} />
      </div>
      <p className="m-0 -mt-1 text-[12px] text-muted-foreground">
        成本的硬上限是"整条链接每天"：访客换浏览器能绕开"每位访客每天"，绕不开它。超限的提问直接拒绝，不调模型。
      </p>

      <div className="flex flex-wrap items-center gap-5">
        <div className="flex items-center gap-2">
          <Switch id="share-citations" checked={values.show_citations} onCheckedChange={(v) => set('show_citations', v === true)} />
          <Label htmlFor="share-citations" className="text-[13px] font-normal">显示引用来源</Label>
        </div>
        <div className="flex items-center gap-2">
          <Switch
            id="share-http-tools"
            checked={values.allow_http_tools}
            onCheckedChange={(v) => { if (v === true) setConfirmTools(true); else set('allow_http_tools', false) }}
          />
          <Label htmlFor="share-http-tools" className="text-[13px] font-normal">允许 HTTP 工具</Label>
        </div>
      </div>

      {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}

      <div>
        <Button variant="primary" size="md" type="submit" disabled={saving}>{saving ? '保存中…' : '保存设置'}</Button>
      </div>

      {/* 打开 HTTP 工具前确认：访客能触发智能体绑定的 HTTP 工具，等于把这些接口开放给拿到链接的人 */}
      <Modal
        open={confirmTools}
        size="sm"
        title="允许访客调用 HTTP 工具？"
        onClose={() => setConfirmTools(false)}
        footer={
          <>
            <Button variant="ghost" size="md" onClick={() => setConfirmTools(false)}>取消</Button>
            <Button variant="primary" size="md" onClick={() => { set('allow_http_tools', true); setConfirmTools(false) }}>允许</Button>
          </>
        }
      >
        <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
          访客的提问会触发智能体绑定的 HTTP 工具（预检里列出了是哪几个），等于把这些接口开放给拿到链接的人。保存后生效。
        </p>
      </Modal>
    </form>
  )
}
