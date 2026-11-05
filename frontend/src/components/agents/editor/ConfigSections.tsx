import { useState, type ReactNode } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'
import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Textarea } from '@/components/shadcn/textarea'
import { compactParams, type AgentDetail, type AgentInput, type ModelRow, type PromptRenderResult, type PromptTemplateRow } from '../../../api'
import AgentTemplateFields from '../../prompt/AgentTemplateFields'
import ModelParamsFields from '../../models/ModelParamsFields'

// 装配页左栏：五个分区卡片（锚点导航用 EDITOR_SECTIONS 的 key 定位）。
// 整页的编辑态由装配页持有（values + onChange），这里只渲染与回传补丁，不发请求。
export const EDITOR_SECTIONS = [
  { key: 'basic', title: '基础信息' }, { key: 'model', title: '模型与参数' }, { key: 'prompt', title: '提示词' },
  { key: 'kb', title: '知识库' }, { key: 'tools', title: '工具' }, { key: 'skills', title: '技能' },
]
export const sectionId = (key: string) => `agent-section-${key}`

export interface Option { value: number; label: string }

// 这三类被引用对象不进发布快照，在各自页面改了立即影响线上（docs/15 3.2"不随发布固化的依赖"）
const liveHint = (what: string) => `${what}本身在${what}页的修改（含启停、删除）不经发布，立即影响线上。`

// 分区卡片：section 上带 id，供左栏锚点跳转
function Section({ id, title, hint, children }: { id: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <section id={sectionId(id)} className="mb-3 rounded-xl border border-border bg-card px-4 py-3.5">
      <h3 className="m-0 text-[14px] font-semibold text-foreground">{title}</h3>
      {hint && <p className="m-0 mt-1 text-[12.5px] leading-relaxed text-muted-foreground">{hint}</p>}
      <div className="mt-3 flex flex-col gap-3.5">{children}</div>
    </section>
  )
}

// 单个字段：标签 + 控件 + 错误（有错时错误顶掉说明文字，避免两行灰字挤在一起）
function Field({ label, htmlFor, error, hint, children }: {
  label: string
  htmlFor?: string
  error?: string
  hint?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={htmlFor} className="text-[13px]">{label}</Label>
      {children}
      {error
        ? <p className="m-0 text-[12.5px] text-destructive">{error}</p>
        : hint && <p className="m-0 text-[12.5px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

// 下拉触发器的统一样式：与 shadcn SelectTrigger 视觉一致
const TRIGGER = 'flex h-9 w-full items-center justify-between gap-2 rounded-md border border-border-strong bg-transparent px-3 text-[13.5px] text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive'

// 单选：Radix 没有内置搜索，这里用 Popover + 过滤框自绘（模型可能有几十个）
function SingleSelect({ value, onChange, options, placeholder, searchable, invalid, emptyText = '没有可选项' }: {
  value?: number
  onChange: (v: number) => void
  options: { value: number; label: string; disabled?: boolean }[]
  placeholder: string
  searchable?: boolean
  invalid?: boolean
  emptyText?: string
}) {
  const [open, setOpen] = useState(false)
  const [keyword, setKeyword] = useState('')
  const selected = options.find((o) => o.value === value)
  const shown = searchable && keyword.trim()
    ? options.filter((o) => o.label.toLowerCase().includes(keyword.trim().toLowerCase()))
    : options
  return (
    <Popover open={open} onOpenChange={(next) => { setOpen(next); if (!next) setKeyword('') }}>
      <PopoverTrigger asChild>
        <button type="button" className={TRIGGER} aria-label={placeholder} aria-invalid={invalid}>
          <span className={`truncate ${selected ? '' : 'text-muted-foreground'}`}>{selected?.label ?? placeholder}</span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[300px] p-1.5">
        {searchable && (
          <div className="relative mb-1">
            <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input autoFocus value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="搜索" className="h-8 pl-7 text-[13px]" />
          </div>
        )}
        <div className="max-h-[260px] overflow-auto">
          {shown.length === 0 && <p className="m-0 px-2 py-1.5 text-[12.5px] text-muted-foreground">{emptyText}</p>}
          {shown.map((o) => (
            <button
              key={o.value}
              type="button"
              disabled={o.disabled}
              onClick={() => { onChange(o.value); setOpen(false) }}
              className="flex w-full items-center justify-between gap-2 rounded px-2 py-1.5 text-left text-[13.5px] hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              <span className="truncate">{o.label}</span>
              {o.value === value && <Check className="size-3.5 shrink-0 text-primary" />}
            </button>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

// 多选：Radix 没有多选，用 Popover + Checkbox 列表；触发器显示已选名称（超过两个折叠成"已选 N 个"）
function MultiSelect({ value = [], onChange, options, placeholder, invalid }: {
  value?: number[]
  onChange: (v: number[]) => void
  options: Option[]
  placeholder: string
  invalid?: boolean
}) {
  const [open, setOpen] = useState(false)
  const selected = options.filter((o) => value.includes(o.value))
  const text = selected.length === 0
    ? placeholder
    : selected.length <= 2 ? selected.map((o) => o.label).join('、') : `已选 ${selected.length} 个`
  const toggle = (id: number) => onChange(value.includes(id) ? value.filter((v) => v !== id) : [...value, id])
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button type="button" className={TRIGGER} aria-label={placeholder} aria-invalid={invalid}>
          <span className={`truncate ${selected.length ? '' : 'text-muted-foreground'}`}>{text}</span>
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[320px] p-1.5">
        <div className="max-h-[280px] overflow-auto">
          {options.length === 0 && <p className="m-0 px-2 py-1.5 text-[12.5px] text-muted-foreground">没有可选项</p>}
          {options.map((o) => (
            <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-[13.5px] hover:bg-accent">
              <Checkbox checked={value.includes(o.value)} onCheckedChange={() => toggle(o.value)} />
              <span className="truncate">{o.label}</span>
            </label>
          ))}
        </div>
      </PopoverContent>
    </Popover>
  )
}

interface Props {
  values: AgentConfigValues
  onChange: (patch: Partial<AgentConfigValues>) => void
  models: ModelRow[]
  kbOptions: Option[]
  toolOptions: Option[]
  skillOptions: Option[]
  templates: PromptTemplateRow[]
  onRenderTemplate: (templateId: number, variables: Record<string, string>) => Promise<PromptRenderResult>
}

/** 装配页的编辑态：草稿 → 表单值（页面持有，保存与调试都取这一份） */
export type AgentConfigValues = ReturnType<typeof toFormValues>

/**
 * 保存前的校验：返回每条错误文案，空对象表示可以保存。
 * 服务端同样会校验，这里只是提前拦住明显不合法的输入。
 */
export function validateAgentConfig(values: AgentConfigValues): Partial<Record<keyof AgentConfigValues, string>> {
  const errors: Partial<Record<keyof AgentConfigValues, string>> = {}
  if (!values.name.trim()) errors.name = '请填写名称'
  else if (values.name.length > 128) errors.name = '名称最多 128 个字符'
  if (!values.model_id) errors.model_id = '请选择模型'
  if ((values.kb_ids ?? []).length > 20) errors.kb_ids = '最多 20 个'
  if ((values.tool_ids ?? []).length > 20) errors.tool_ids = '最多 20 个'
  if ((values.skill_ids ?? []).length > 20) errors.skill_ids = '最多 20 个'
  return errors
}

export default function ConfigSections({ values, onChange, models, kbOptions, toolOptions, skillOptions, templates, onRenderTemplate }: Props) {
  // 一进页面就飘红太吵：只有用户碰过（失焦过）的字段才显示错误
  const [touched, setTouched] = useState<Partial<Record<keyof AgentConfigValues, boolean>>>({})
  const touch = (key: keyof AgentConfigValues) => setTouched((t) => ({ ...t, [key]: true }))
  const errors = validateAgentConfig(values)
  const errorOf = (key: keyof AgentConfigValues) => (touched[key] ? errors[key] : undefined)

  return (
    <>
      <Section id="basic" title="基础信息">
        <Field label="名称" htmlFor="agent-name" error={errorOf('name')}>
          <Input
            id="agent-name"
            value={values.name}
            placeholder="例如：客服助手"
            aria-invalid={!!errorOf('name')}
            onChange={(e) => onChange({ name: e.target.value })}
            onBlur={() => touch('name')}
          />
        </Field>
        <Field label="描述" htmlFor="agent-desc" hint="写清楚这个智能体做什么、给谁用，发布后出现在对外资料里">
          <Textarea
            id="agent-desc"
            rows={3}
            value={values.description}
            placeholder="这个智能体做什么、给谁用"
            className="resize-y text-[13.5px]"
            onChange={(e) => onChange({ description: e.target.value })}
          />
        </Field>
      </Section>

      <Section id="model" title="模型与参数" hint={liveHint('模型')}>
        <Field label="模型" error={errorOf('model_id')}>
          <SingleSelect
            searchable
            placeholder="选择模型"
            invalid={!!errorOf('model_id')}
            value={values.model_id}
            onChange={(id) => { onChange({ model_id: id }); touch('model_id') }}
            options={models.map((m) => ({ value: m.id, label: m.is_enabled ? m.name : `${m.name}（已停用）`, disabled: !m.is_enabled }))}
          />
        </Field>
        <div className="flex flex-col gap-1.5">
          <ModelParamsFields
            value={values.params}
            onChange={(params) => onChange({ params })}
            inherited={models.find((m) => m.id === values.model_id)?.default_params ?? {}}
          />
          <p className="m-0 text-[12.5px] text-muted-foreground">留空继承模型默认；不同厂商支持的取值范围不同。</p>
        </div>
      </Section>

      <Section id="prompt" title="提示词">
        <AgentTemplateFields values={values} onChange={onChange} templates={templates} onRender={onRenderTemplate} />
      </Section>

      <Section id="kb" title="知识库" hint={liveHint('知识库')}>
        <Field label="检索的知识库" error={errorOf('kb_ids')} hint="对话时先检索这些知识库，再把片段注入提示词">
          <MultiSelect
            value={values.kb_ids}
            onChange={(ids) => { onChange({ kb_ids: ids }); touch('kb_ids') }}
            options={kbOptions}
            placeholder="未绑定知识库"
            invalid={!!errorOf('kb_ids')}
          />
        </Field>
      </Section>

      <Section id="tools" title="工具" hint={liveHint('工具')}>
        <Field label="HTTP 工具" error={errorOf('tool_ids')} hint="内置的时间与计算器工具总是可用；这里绑定自定义 HTTP 工具">
          <MultiSelect
            value={values.tool_ids}
            onChange={(ids) => { onChange({ tool_ids: ids }); touch('tool_ids') }}
            options={toolOptions}
            placeholder="未绑定 HTTP 工具"
            invalid={!!errorOf('tool_ids')}
          />
        </Field>
      </Section>

      {/* 技能与提示词分开：模板是「人设」，技能是「操作手册」，混在一张卡片里会让人以为是同一种东西 */}
      <Section
        id="skills"
        title="技能"
        hint={`技能只在需要时加载，不占常驻上下文；开启「常驻」的技能正文每轮都进提示词。${liveHint('技能')}`}
      >
        <Field
          label="可用的技能"
          error={errorOf('skill_ids')}
          hint="模型先看到技能名与说明，遇到对应任务时再调 load_skill 取正文"
        >
          <MultiSelect
            value={values.skill_ids}
            onChange={(ids) => { onChange({ skill_ids: ids }); touch('skill_ids') }}
            options={skillOptions}
            placeholder="未绑定技能"
            invalid={!!errorOf('skill_ids')}
          />
        </Field>
      </Section>
    </>
  )
}

// 草稿 → 表单值。workflow_id 没有表单项，放进编辑态只为保存时原样带回（PUT 是整体覆盖）
export function toFormValues(a: AgentDetail) {
  return {
    name: a.name, description: a.description ?? '', system_prompt: a.system_prompt, model_id: a.model_id, params: a.params ?? {},
    kb_ids: a.kb_ids ?? [], tool_ids: a.tool_ids ?? [], skill_ids: a.skill_ids ?? [], workflow_id: a.workflow_id,
    use_template: !!a.prompt_template_id, prompt_template_id: a.prompt_template_id, prompt_variables: a.prompt_variables ?? {},
  }
}

// 表单值 → 保存请求。手填与模板二选一：用模板时 system_prompt 传空串由后端渲染；留空的参数键不提交（继承模型默认）
export function toPayload(values: Record<string, unknown>): AgentInput {
  const { use_template: useTemplate, ...rest } = values
  const base = rest as unknown as AgentInput
  const payload: AgentInput = useTemplate
    ? { ...base, system_prompt: '', prompt_variables: base.prompt_variables || {} }
    : { ...base, prompt_template_id: null, prompt_variables: {} }
  return { ...payload, params: compactParams(payload.params) }
}
