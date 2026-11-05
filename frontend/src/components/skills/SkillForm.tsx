import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { createSkill, updateSkill, type ParsedSkill, type SkillInput, type SkillRow } from '../../api'
import { errorText } from '../../utils/errors'
import SkillResources from './SkillResources'

// 技能新增 / 编辑：正文是 Markdown 操作手册，动辄几百行 → 用抽屉（整高、正文滚动、按钮常驻），不用弹窗。
// 三处必须在界面上说清（docs/17 §4）：
//   1. name 是模型 load_skill(name) 唯一能传的标识，格式被后端正则锁死，前端只做提前提示；
//   2. description 决定模型会不会用这个技能（它只先看到 name + description 这一层目录）；
//   3. 正文按 UTF-8 字节限 64KB（中文一个字 3 字节，按字数算会超出一倍）。
interface Props {
  open: boolean
  editing: SkillRow | null
  /** 导入 SKILL.md 解析出的字段：只用于新建态预填，确认后照常走 createSkill */
  prefill?: ParsedSkill | null
  onClose: () => void
  onSaved: () => void
}
interface FormValues {
  name: string
  display_name: string
  description: string
  content: string
  always_on: boolean
  is_enabled: boolean
}

// 与后端 SKILL_NAME_PATTERN 同一条正则：小写字母数字与连字符，不以连字符开头/结尾、不连续连字符
const NAME_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/
const NAME_MAX = 64
const DESCRIPTION_MAX = 1024
const CONTENT_MAX_BYTES = 64 * 1024

const EMPTY: FormValues = { name: '', display_name: '', description: '', content: '', always_on: false, is_enabled: true }

// 与服务端 _check_content_size 同一算法：按 UTF-8 字节数算，不是字符数
const utf8Bytes = (s: string) => new TextEncoder().encode(s).length
const kbText = (bytes: number) => `${(bytes / 1024).toFixed(1)}KB`

export default function SkillForm({ open, editing, prefill, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bytes = useMemo(() => utf8Bytes(values.content), [values.content])
  const overLimit = bytes > CONTENT_MAX_BYTES
  const nameInvalid = !!values.name && !NAME_PATTERN.test(values.name)

  useEffect(() => {
    if (!open) return
    setError(null)
    if (editing) {
      setValues({
        name: editing.name, display_name: editing.display_name, description: editing.description || '',
        content: editing.content || '', always_on: editing.always_on, is_enabled: editing.is_enabled,
      })
    } else if (prefill) {
      // 导入的技能 always_on 由解析结果给（默认关）：长手册常驻会把上下文占满
      setValues({
        name: prefill.name, display_name: prefill.display_name, description: prefill.description,
        content: prefill.content, always_on: prefill.always_on, is_enabled: prefill.is_enabled,
      })
    } else {
      setValues(EMPTY)
    }
  }, [open, editing, prefill])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  // 服务端同样会校验（422 / 400 / 409），这里只是提前给出可读提示
  const validate = (v: FormValues): string | null => {
    if (!v.display_name.trim()) return '请填写显示名'
    if (!v.name.trim()) return '请填写 name'
    if (!NAME_PATTERN.test(v.name)) return 'name 只能用小写字母、数字与连字符（如 web-page-builder），不能以连字符开头或结尾，也不能出现连续连字符'
    if (v.name.length > NAME_MAX) return `name 最多 ${NAME_MAX} 个字符`
    if (!v.description.trim()) return '请填写描述：模型据此判断要不要加载这个技能'
    if (v.description.length > DESCRIPTION_MAX) return `描述最多 ${DESCRIPTION_MAX} 个字符`
    if (!v.content.trim()) return '请填写技能正文'
    if (utf8Bytes(v.content) > CONTENT_MAX_BYTES) return `技能正文最多 64KB，当前 ${kbText(utf8Bytes(v.content))}`
    return null
  }

  const onSubmit = async () => {
    const invalid = validate(values)
    if (invalid) { setError(invalid); return }
    // PUT 是整体覆盖：字段一个不少地发上去，漏了会被服务端拒或清空。
    // resources 不在这个请求体里（服务端 extra=forbid）：资源走子接口单独增删，保存技能不会动脚本
    const payload: SkillInput = {
      name: values.name.trim(),
      display_name: values.display_name.trim(),
      description: values.description.trim(),
      content: values.content,
      always_on: values.always_on,
      is_enabled: values.is_enabled,
    }
    setSubmitting(true)
    try {
      if (editing) await updateSkill(editing.id, payload)
      else await createSkill(payload)
      toast.success(editing ? '保存成功' : '创建成功')
      onSaved()
      onClose()
    } catch (e) {
      // 409 重名 / 400 正文超限：把后端 detail 原样上屏
      setError(errorText(e, '保存失败'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={800}
      title={editing ? `编辑技能：${editing.display_name}（当前 v${editing.version}）` : '新增技能'}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting || overLimit} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex gap-3">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="skill-display-name">显示名</Label>
            <Input id="skill-display-name" value={values.display_name} maxLength={128} onChange={(e) => set('display_name', e.target.value)} placeholder="例如：网页制作手册" />
            <p className="m-0 text-[12px] text-muted-foreground">只给人在列表和装配页里看，模型看不到</p>
          </div>
          <div className="flex w-[280px] flex-col gap-1.5">
            <Label htmlFor="skill-name">name</Label>
            <Input
              id="skill-name"
              value={values.name}
              maxLength={NAME_MAX}
              onChange={(e) => set('name', e.target.value)}
              placeholder="web-page-builder"
              aria-invalid={nameInvalid}
              className="font-mono text-[13px]"
            />
            <p className="m-0 text-[12px] text-muted-foreground">
              只能用小写字母、数字与连字符（<code className="font-mono">^[a-z0-9]+(-[a-z0-9]+)*$</code>）；
              它是模型调用 <code className="font-mono">load_skill</code> 时唯一能传的标识，带大写或空格会让它频繁传错
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="skill-desc">描述（模型据此决定要不要用这个技能）</Label>
          <textarea
            id="skill-desc"
            rows={3}
            value={values.description}
            maxLength={DESCRIPTION_MAX}
            onChange={(e) => set('description', e.target.value)}
            placeholder="一句话说清这个手册覆盖哪类任务、什么时候该查它"
            className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-[13px] leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <p className="m-0 text-[12px] text-muted-foreground">
            模型平时只看到 name 与这段描述（约 100 token / 个），要用了才加载正文；写得含糊它就不会调用。最多 {DESCRIPTION_MAX} 个字符，当前 {values.description.length}
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-3">
            <Label htmlFor="skill-content">正文（Markdown）</Label>
            <span className={overLimit ? 'text-[12px] text-destructive' : 'text-[12px] text-muted-foreground'}>
              {kbText(bytes)} / 64KB
            </span>
          </div>
          {/* 正文用原生 textarea（与提示词模板页同一写法）：shadcn 的 Textarea 带 field-sizing-content，
              几十 KB 的正文会被撑成一屏高的巨块；这里固定 16 行、可手动拖高，滚动只发生在框内 */}
          <textarea
            id="skill-content"
            rows={16}
            value={values.content}
            onChange={(e) => set('content', e.target.value)}
            placeholder={'# 何时使用\n…\n\n## 步骤\n1. …'}
            aria-invalid={overLimit}
            className={`w-full resize-y rounded-lg border bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 ${overLimit ? 'border-destructive' : 'border-input focus-visible:border-ring'}`}
          />
          <p className="m-0 text-[12px] text-muted-foreground">
            上限按 UTF-8 字节算（中文一个字 3 字节）。开启「常驻」后这段正文每轮都进提示词；不开则只在需要时由模型调 <code className="font-mono">load_skill</code> 取
          </p>
        </div>

        <div className="flex flex-col gap-3 rounded-lg border border-border px-3 py-3">
          <ToggleRow
            id="skill-always-on"
            label="常驻（正文每轮都进系统提示词）"
            hint="适合输出格式约定这类每轮都要遵守的规则；按需加载只在模型判断需要时才取正文，不占常驻上下文"
            checked={values.always_on}
            onChange={(v) => set('always_on', v)}
          />
          <ToggleRow
            id="skill-enabled"
            label="启用"
            hint="停用后绑定关系保留，但模型不再看到这个技能；重新启用即恢复"
            checked={values.is_enabled}
            onChange={(v) => set('is_enabled', v)}
          />
        </div>

        {/* 资源区只在编辑态：资源挂在 /skills/{id}/resources 下，新建时还没有 id */}
        {editing ? (
          <SkillResources skillId={editing.id} onChanged={onSaved} />
        ) : (
          <p className="m-0 text-[12px] text-muted-foreground">保存后可以给这个技能上传脚本资源。</p>
        )}

        {editing && (
          <p className="m-0 text-[12px] text-muted-foreground">
            技能没有发布流程：保存后立刻对所有绑定它的线上智能体生效；改 name / 描述 / 正文会自动升版本，只改显示名或开关不升版本。
          </p>
        )}

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </div>
    </Drawer>
  )
}

// 开关行：不用 shadcn Switch 的默认尺寸（行高会被撑高），这里用项目自绘的紧凑开关，与列表里的启停开关同一视觉
function ToggleRow({ id, label, hint, checked, onChange }: {
  id: string
  label: string
  hint: string
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <label htmlFor={id} className="text-[13px] font-medium">{label}</label>
        <p className="m-0 mt-0.5 text-[12px] text-muted-foreground">{hint}</p>
      </div>
      <button
        type="button"
        id={id}
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className="relative mt-0.5 shrink-0 rounded-full transition-colors after:absolute after:-inset-[13px] after:content-['']"
        style={{ width: 32, height: 18, background: checked ? 'var(--accent)' : 'var(--border-strong)' }}
      >
        <span
          className="absolute rounded-full bg-white transition-transform"
          style={{ width: 14, height: 14, top: 2, left: 2, transform: checked ? 'translateX(14px)' : 'none' }}
        />
      </button>
    </div>
  )
}
