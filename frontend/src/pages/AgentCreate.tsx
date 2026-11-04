import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Bot, Check, ChevronDown, Search } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { createAgent, listModels, OPTIONS_PAGE, type ModelRow } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useGuardedNavigate } from '../hooks/useGuardedNavigate'
import { useUnsaved } from '../store/unsaved'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Textarea } from '@/components/shadcn/textarea'
import PageHeader from '../components/layout/PageHeader'
import ErrorState from '../components/common/ErrorState'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

// 新建智能体 /agents/new（docs/15 D-10 先建后编）：只填名称、模型、描述，存成草稿后进装配页配置提示词、知识库、工具。
// 草稿不上线，先建没有风险；调试也要挂在已有的智能体下才能按智能体算成本。
// 保留为独立页面（路由已经是 /agents/new），三个字段但不适合弹窗：创建完要直接进装配页，页面切换比弹窗顺。
export default function AgentCreate() {
  const navigate = useNavigate()
  const guardedNavigate = useGuardedNavigate()
  const setDirty = useUnsaved((s) => s.setDirty)
  const models = useAsyncData(() => listModels(OPTIONS_PAGE), [], { errorText: '加载模型失败' })
  const [saving, setSaving] = useState(false)
  const [values, setValues] = useState<{ name: string; model_id?: number; description: string }>({ name: '', model_id: undefined, description: '' })
  const [errors, setErrors] = useState<{ name?: string; model_id?: string; description?: string }>({})

  const set = <K extends keyof typeof values>(key: K, v: (typeof values)[K]) => {
    setValues((s) => ({ ...s, [key]: v }))
    setErrors((e) => (e[key] ? { ...e, [key]: undefined } : e))
  }
  // 有内容才算"有未保存的修改"，用来拦后退（原页面同样口径）
  const filled = !!(values.name || values.model_id || values.description)
  useEffect(() => { setDirty(filled) }, [filled, setDirty])
  useEffect(() => () => setDirty(false), [setDirty])

  const onCreate = async () => {
    const next: typeof errors = {}
    if (!values.name.trim()) next.name = '请填写名称'
    else if (values.name.length > 128) next.name = '名称最多 128 个字符'
    if (!values.model_id) next.model_id = '请选择模型'
    if (values.description.length > 2000) next.description = '描述最多 2000 个字符'
    if (Object.keys(next).length) { setErrors(next); return }

    setSaving(true)
    try {
      const created = await createAgent({ name: values.name.trim(), model_id: values.model_id!, description: values.description || '' })
      setDirty(false)
      toast.success('已创建草稿，继续装配')
      navigate(`/agents/${created.id}/edit`, { replace: true })
    } catch (e) {
      toast.error(errorText(e, '创建失败'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="shrink-0">
        <PageHeader icon={<Bot />} crumbs={[{ label: '智能体', to: '/agents' }, { label: '新建' }]} title="新建智能体"
          description="先定名称与模型，创建后进入装配页配置提示词、知识库与工具，并可当场调试；发布后才对外可用。" />
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="max-w-[640px] rounded-xl border border-border bg-card px-5 py-4">
          {models.error && <div className="mb-3"><ErrorState compact message={models.error} onRetry={() => models.reload()} /></div>}

          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-agent-name" className="text-[13px]">名称</Label>
              <Input
                id="new-agent-name"
                autoFocus
                value={values.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="例如：客服助手"
                aria-invalid={!!errors.name}
              />
              {errors.name && <p className="m-0 text-[12.5px] text-destructive">{errors.name}</p>}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label className="text-[13px]">模型</Label>
              <ModelSelect
                value={values.model_id}
                onChange={(id) => set('model_id', id)}
                loading={models.loading}
                models={models.data?.items ?? []}
                invalid={!!errors.model_id}
              />
              {errors.model_id
                ? <p className="m-0 text-[12.5px] text-destructive">{errors.model_id}</p>
                : <p className="m-0 text-[12.5px] text-muted-foreground">模型参数可在装配页按智能体覆盖</p>}
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="new-agent-desc" className="text-[13px]">描述</Label>
              <Textarea
                id="new-agent-desc"
                rows={3}
                value={values.description}
                onChange={(e) => set('description', e.target.value)}
                placeholder="这个智能体做什么、给谁用"
                className="resize-y text-[13.5px]"
                aria-invalid={!!errors.description}
              />
              {errors.description && <p className="m-0 text-[12.5px] text-destructive">{errors.description}</p>}
            </div>

            <div className="flex items-center gap-2 pt-1">
              <Button variant="primary" size="md" disabled={saving} onClick={onCreate}>{saving ? '创建中…' : '创建并进入装配'}</Button>
              <Button variant="secondary" size="md" onClick={() => guardedNavigate('/agents')}>取消</Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// 模型单选：停用的模型也列出来但不可选（原页面的行为）；模型可能很多，所以带搜索
function ModelSelect({ value, onChange, models, loading, invalid }: {
  value?: number
  onChange: (id: number) => void
  models: ModelRow[]
  loading?: boolean
  invalid?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const selected = models.find((m) => m.id === value)
  const shown = keyword.trim() ? models.filter((m) => m.name.toLowerCase().includes(keyword.trim().toLowerCase())) : models
  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) setKeyword('') }}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="选择模型"
          aria-invalid={invalid}
          className="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border-strong bg-transparent px-3 text-[13.5px] text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive"
        >
          <span className={`truncate ${selected ? '' : 'text-muted-foreground'}`}>{selected ? selected.name : '选择模型'}</span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[320px] p-1.5">
        <div className="relative mb-1">
          <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input autoFocus value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索模型" className="h-8 pl-7 text-[13px]" />
        </div>
        <div className="max-h-[260px] overflow-auto">
          {loading && <p className="m-0 px-2 py-1.5 text-[12.5px] text-muted-foreground">加载中…</p>}
          {!loading && shown.length === 0 && <p className="m-0 px-2 py-1.5 text-[12.5px] text-muted-foreground">没有可用的模型</p>}
          {shown.map((m) => (
            <button
              key={m.id}
              type="button"
              disabled={!m.is_enabled}
              onClick={() => { onChange(m.id); setOpen(false) }}
              className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[13.5px] hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="truncate">{m.is_enabled ? m.name : `${m.name}（已停用）`}</span>
              {m.id === value && <Check className="size-3.5 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}
