import { useState } from 'react'
import { toast } from 'sonner'
import { TriangleAlert, Wand2 } from 'lucide-react'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Switch } from '@/components/shadcn/switch'
import Button from '../ui/Button'
import type { PromptRenderResult, PromptTemplateRow } from '../../api'
import { errorText } from '../../utils/errors'

// 智能体装配页的提示词区块（FR-028）："从模板生成"开关：开启后选模板、按声明填变量、只读展示渲染结果，
// system_prompt 不再手填（提交时传空串由后端渲染）；关闭后恢复手填。渲染预览的请求由页面注入（组件不发请求）。
// 受控：值与回传都由装配页持有的 values / onChange 决定。

/** 本组件用到的字段，装配页的值对象是它的超集 */
export interface TemplateFieldValues {
  use_template: boolean
  prompt_template_id: number | null
  prompt_variables: Record<string, string>
  system_prompt: string
}

interface Props {
  values: TemplateFieldValues
  onChange: (patch: Partial<TemplateFieldValues>) => void
  templates: PromptTemplateRow[]
  onRender: (templateId: number, variables: Record<string, string>) => Promise<PromptRenderResult>
}

export default function AgentTemplateFields({ values, onChange, templates, onRender }: Props) {
  const [preview, setPreview] = useState<PromptRenderResult | null>(null)
  const [rendering, setRendering] = useState(false)
  const selected = templates.find((t) => t.id === values.prompt_template_id)

  const doPreview = async () => {
    if (!values.prompt_template_id) return
    setRendering(true)
    try {
      setPreview(await onRender(values.prompt_template_id, values.prompt_variables || {}))
    } catch (e) {
      toast.error(errorText(e, '渲染失败'))
    } finally {
      setRendering(false)
    }
  }

  const setVariable = (name: string, v: string) => onChange({ prompt_variables: { ...(values.prompt_variables || {}), [name]: v } })

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-3">
        <div>
          <Label htmlFor="use-template" className="text-[13px]">提示词来源</Label>
          <p className="m-0 mt-1 text-[12px] text-muted-foreground">开启后按模板渲染，关闭则手写系统提示词</p>
        </div>
        <Switch
          id="use-template"
          checked={!!values.use_template}
          onCheckedChange={(on) => {
            setPreview(null)
            onChange({ use_template: on, prompt_variables: {} })
          }}
        />
      </div>

      {values.use_template ? (
        <>
          <div className="flex flex-col gap-1.5">
            <Label className="text-[13px]">模板</Label>
            <select
              value={values.prompt_template_id ?? ''}
              onChange={(e) => {
                setPreview(null)
                onChange({ prompt_template_id: e.target.value ? Number(e.target.value) : null, prompt_variables: {} })
              }}
              className="h-9 w-full rounded-md border border-border-strong bg-transparent px-2.5 text-[13.5px] text-foreground outline-none focus-visible:border-ring"
            >
              <option value="">选择提示词模板</option>
              {templates.map((t) => <option key={t.id} value={t.id}>{t.name}（v{t.version}）</option>)}
            </select>
          </div>

          {(selected?.variables || []).map((v) => (
            <div key={v.name} className="flex flex-col gap-1.5">
              <Label className="text-[13px]">
                {v.name}
                {v.required && !v.default && <span className="ml-0.5 text-destructive">*</span>}
                {v.description && <span className="ml-1 text-[12px] font-normal text-muted-foreground">（{v.description}）</span>}
              </Label>
              <Input
                value={values.prompt_variables?.[v.name] ?? ''}
                placeholder={v.default ? '默认：' + v.default : ''}
                className="h-9 text-[13.5px]"
                onChange={(e) => setVariable(v.name, e.target.value)}
              />
            </div>
          ))}

          <div>
            <Button size="sm" variant="secondary" icon={<Wand2 />} disabled={!values.prompt_template_id || rendering} onClick={doPreview}>
              {rendering ? '渲染中…' : '预览渲染结果'}
            </Button>
          </div>

          {preview && (
            <div className="flex flex-col gap-2">
              {/* 缺必填变量时接口直接 400，不会走到这里；unused 是模板本身的问题，填了也不起作用 */}
              {preview.unused.length > 0 && (
                <div className="flex items-start gap-2 rounded-lg border border-[rgba(217,119,6,.35)] bg-[rgba(217,119,6,.10)] px-3 py-2">
                  <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-[#B45309]" />
                  <span className="text-[12.5px] leading-relaxed">模板声明了这些变量，但内容里没有引用，填了也不起作用：{preview.unused.join('、')}</span>
                </div>
              )}
              <pre className="m-0 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-secondary p-3 text-[13px] leading-relaxed text-foreground">{preview.content}</pre>
            </div>
          )}

          <p className="m-0 text-[12px] leading-relaxed text-muted-foreground">保存草稿时按模板当前版本渲染进系统提示词；模板改版后不会自动更新，需重新保存草稿并发布。</p>
        </>
      ) : (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="system-prompt" className="text-[13px]">系统提示词</Label>
          <textarea
            id="system-prompt"
            rows={8}
            maxLength={20000}
            value={values.system_prompt}
            onChange={(e) => onChange({ system_prompt: e.target.value })}
            className="w-full resize-y rounded-md border border-border-strong bg-transparent px-3 py-2 text-[13.5px] leading-relaxed text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <p className="m-0 text-right text-[12px] text-muted-foreground">{(values.system_prompt || '').length} / 20000</p>
        </div>
      )}
    </div>
  )
}
