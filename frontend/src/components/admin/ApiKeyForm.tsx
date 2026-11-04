import { useEffect, useState } from 'react'
import { ChevronsUpDown, TriangleAlert, X } from 'lucide-react'
import { toast } from 'sonner'
import { Alert, AlertDescription, AlertTitle } from '@/components/shadcn/alert'
import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Textarea } from '@/components/shadcn/textarea'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { createApiKey, updateApiKey, type ApiKeyInput, type ApiKeyRow, type ApiKeyScopeItem } from '../../api'
import type { ScopeOptions } from '../../hooks/useApiKeyScopeOptions'
import { errorText } from '../../utils/errors'

// API Key 生成 / 编辑抽屉：授权范围（至少一项，docs/15 3.7.1）+ 配额、来源白名单、限速。字段多，用抽屉。
// 白名单用多行文本承载（一行一条），提交前拆成数组；CIDR、范围与作用域的合法性由服务端兜底（422 / 400）。作用域选项由页面取好传入。
// initialScope：新建时预填的作用域（智能体"发布渠道"里生成仅限此智能体的 Key）
// ownerOptions：只有 admin 的 API Key 页传，新建时可以代发给某个用户（docs/15 D-15，Key 归属该用户，对方在个人中心只读查看）
interface Props {
  open: boolean; editing: ApiKeyRow | null; scopeOptions: ScopeOptions; initialScope?: Pick<ApiKeyInput, 'agent_ids'> | Pick<ApiKeyInput, 'workflow_ids'>
  ownerOptions?: { value: number; label: string }[]
  onClose: () => void; onSaved: () => void; onCreated: (key: string) => void
}
interface FormValues { name: string; owner: string; quota: number; rate: number; ips: string; agent_ids: number[]; workflow_ids: number[]; kb_ids: number[] }
const EMPTY: FormValues = { name: '', owner: 'self', quota: 1000, rate: 0, ips: '', agent_ids: [], workflow_ids: [], kb_ids: [] }
const splitIps = (text: string): string[] => text.split(/\r?\n/).map((s) => s.trim()).filter(Boolean)

// 授权范围的多选：shadcn 没有多选下拉，用 Popover + 搜索框 + 复选框列表，已选项在下方以可移除的标签展示。
// 已删除 / 不在候选第一页的资源也要能显示名字（否则只剩一个数字），统一显示为"已删除 #id"。
interface PickerProps {
  label: string; hint: string; placeholder: string
  options: { id: number; name: string }[]
  /** 编辑时已有的授权项，名字为 null 表示资源已删除 */
  current?: ApiKeyScopeItem[]
  value: number[]; loading: boolean; onChange: (ids: number[]) => void
}

function ScopePicker({ label, hint, placeholder, options, current, value, loading, onChange }: PickerProps) {
  const [keyword, setKeyword] = useState('')
  const known = new Set(options.map((o) => o.id))
  const extras = (current ?? []).filter((c) => !known.has(c.id) && value.includes(c.id))
    .map((c) => ({ id: c.id, name: c.name ?? `已删除 #${c.id}` }))
  const all = [...options, ...extras]
  const keywordText = keyword.trim()
  const shown = keywordText ? all.filter((o) => o.name.includes(keywordText)) : all
  const toggle = (id: number) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])

  return (
    <div className="flex flex-col gap-1.5">
      <Label>{label}</Label>
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="flex h-9 w-full items-center justify-between gap-2 rounded-lg border border-input bg-transparent px-3 text-left text-[13px] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          >
            <span className={value.length ? 'truncate text-foreground' : 'truncate text-muted-foreground'}>
              {value.length ? `已选 ${value.length} 项` : placeholder}
            </span>
            <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-[360px] p-0">
          <div className="border-b border-border p-2">
            <Input value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索名称" className="h-8 text-[13px]" />
          </div>
          <div className="max-h-56 overflow-y-auto p-1">
            {loading && <p className="m-0 px-2 py-3 text-[12.5px] text-muted-foreground">加载中…</p>}
            {!loading && shown.length === 0 && <p className="m-0 px-2 py-3 text-[12.5px] text-muted-foreground">没有匹配的资源</p>}
            {!loading && shown.map((o) => (
              <label key={o.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-accent">
                <Checkbox checked={value.includes(o.id)} onCheckedChange={() => toggle(o.id)} />
                <span className="min-w-0 truncate text-[13px] text-foreground">{o.name}</span>
              </label>
            ))}
          </div>
          <div className="flex items-center justify-between border-t border-border px-2 py-1.5">
            <span className="text-[12px] text-muted-foreground">已选 {value.length} 项</span>
            {value.length > 0 && (
              <button type="button" className="text-[12px] text-muted-foreground hover:text-foreground" onClick={() => onChange([])}>清空</button>
            )}
          </div>
        </PopoverContent>
      </Popover>

      {value.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {all.filter((o) => value.includes(o.id)).map((o) => (
            <span key={o.id} className="inline-flex items-center gap-1 rounded-full bg-secondary px-2 py-[1px] text-[11.5px] text-foreground">
              {o.name}
              <button type="button" aria-label={`移除 ${o.name}`} className="text-muted-foreground hover:text-destructive" onClick={() => toggle(o.id)}>
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <p className="m-0 text-[12px] text-muted-foreground">{hint}</p>
    </div>
  )
}

export default function ApiKeyForm({ open, editing, scopeOptions, initialScope, ownerOptions, onClose, onSaved, onCreated }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setValues(editing
      ? {
          name: editing.name, owner: 'self', quota: editing.quota, rate: editing.rate_limit_per_minute,
          ips: editing.allowed_ips.join('\n'),
          agent_ids: editing.agent_ids, workflow_ids: editing.workflow_ids, kb_ids: editing.kb_ids,
        }
      : { ...EMPTY, ...(initialScope ?? {}) })
    // initialScope 只在打开时读一次：父组件每次渲染都传一个新对象，放进依赖会把正在填的表单反复重置
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  // 预检：所选智能体绑定、但既不公开也没放行给这个 Key 的库，对话里检索不到（按智能体草稿的绑定估算）
  const kbById = new Map(scopeOptions.kbs.map((k) => [k.id, k]))
  const blind = [...new Set(scopeOptions.agents.filter((a) => values.agent_ids.includes(a.id)).flatMap((a) => a.kb_ids))]
    .filter((id) => !values.kb_ids.includes(id) && kbById.get(id)?.is_public === false)
    .map((id) => kbById.get(id)?.name ?? `#${id}`)

  const onSubmit = async () => {
    // 服务端同样会校验（400 / 422），这里只是提前给出可读提示
    if (!values.name.trim()) { setError('请填写名称'); return }
    if (!values.agent_ids.length && !values.workflow_ids.length && !values.kb_ids.length) { setError('至少授权一个智能体、工作流或知识库'); return }
    const payload: ApiKeyInput = {
      name: values.name.trim(), quota: values.quota, allowed_ips: splitIps(values.ips), rate_limit_per_minute: values.rate,
      agent_ids: values.agent_ids, workflow_ids: values.workflow_ids, kb_ids: values.kb_ids,
      ...(!editing && values.owner !== 'self' ? { owner_user_id: Number(values.owner) } : {}),
    }
    setSubmitting(true)
    try {
      if (editing) { await updateApiKey(editing.id, payload); toast.success('已保存') }
      else { const res = await createApiKey(payload); onCreated(res.key) }
      onSaved()
      onClose()
    } catch (e) { toast.error(errorText(e, editing ? '保存失败' : '创建失败')) } finally { setSubmitting(false) }
  }

  return (
    <Drawer
      open={open}
      width={720}
      title={editing ? `编辑 API Key：${editing.name}` : '生成 API Key'}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : editing ? '保存' : '生成'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="key-name">名称</Label>
          <Input id="key-name" value={values.name} maxLength={64} placeholder="如：生产环境调用" onChange={(e) => set('name', e.target.value)} />
        </div>

        {!editing && ownerOptions && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="key-owner">发放给</Label>
            <Select value={values.owner} onValueChange={(v) => set('owner', v)}>
              <SelectTrigger id="key-owner" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="self">不指定（归属我自己）</SelectItem>
                {ownerOptions.map((o) => <SelectItem key={o.value} value={String(o.value)}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="m-0 text-[12px] text-muted-foreground">不选则归属你自己。代发的 Key 以对方的身份与角色调用，知识库按对方能看到的校验；对方在个人中心只读查看，停用找管理员</p>
          </div>
        )}

        <h3 className="m-0 text-[13px] font-semibold text-foreground">授权范围（只能调用这里的资源）</h3>
        {scopeOptions.error && (
          <Alert variant="destructive">
            <TriangleAlert />
            <AlertTitle>加载可授权的资源失败</AlertTitle>
            <AlertDescription>{scopeOptions.error}</AlertDescription>
          </Alert>
        )}
        <ScopePicker
          label="可调用的智能体"
          hint="只能对话这里列出的智能体（未发布的调用时仍会被拒）"
          placeholder="选择智能体"
          options={scopeOptions.agents}
          current={editing?.scope.agents}
          value={values.agent_ids}
          loading={scopeOptions.loading}
          onChange={(ids) => set('agent_ids', ids)}
        />
        <ScopePicker
          label="可运行的工作流"
          hint="运行与续跑都只限这里；续跑只能续本 Key 发起的运行"
          placeholder="选择工作流"
          options={scopeOptions.workflows}
          current={editing?.scope.workflows}
          value={values.workflow_ids}
          loading={scopeOptions.loading}
          onChange={(ids) => set('workflow_ids', ids)}
        />
        <ScopePicker
          label="检索放行的非公开知识库"
          hint="对话检索只放行公开库与这里的库；只能选你看得到的库"
          placeholder="选择知识库"
          options={scopeOptions.kbs}
          current={editing?.scope.knowledge_bases}
          value={values.kb_ids}
          loading={scopeOptions.loading}
          onChange={(ids) => set('kb_ids', ids)}
        />
        {blind.length > 0 && (
          <Alert className="border-border-strong">
            <TriangleAlert className="text-muted-foreground" />
            <AlertTitle>这些库对该 Key 检索不到：{blind.join('、')}</AlertTitle>
            <AlertDescription>所选智能体绑定了它们，但它们不公开、也没有放行给这个 Key；需要的话加到上面的“检索放行的非公开知识库”。</AlertDescription>
          </Alert>
        )}

        <h3 className="m-0 text-[13px] font-semibold text-foreground">配额与来源</h3>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="key-quota">配额（调用次数）</Label>
          <Input id="key-quota" type="number" min={0} value={values.quota} onChange={(e) => set('quota', Number(e.target.value))} />
          <p className="m-0 text-[12px] text-muted-foreground">每次成功进入业务接口的请求消耗 1 次；用完后 403，编辑配额可续</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="key-ips">允许的来源 IP（一行一条，IP 或 CIDR；留空不限制）</Label>
          <Textarea id="key-ips" rows={3} value={values.ips} placeholder={'10.20.0.0/16\n203.0.113.8'} className="font-mono text-[13px]" onChange={(e) => set('ips', e.target.value)} />
          <p className="m-0 text-[12px] text-muted-foreground">不在名单内的来源会被拒绝（403）且不扣配额。最多 50 条。</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="key-rate">每分钟限速</Label>
          <Input id="key-rate" type="number" min={0} max={10000} value={values.rate} onChange={(e) => set('rate', Number(e.target.value))} />
          <p className="m-0 text-[12px] text-muted-foreground">0 表示使用服务端全局默认；超限返回 429 且不扣配额。</p>
        </div>

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </div>
    </Drawer>
  )
}
