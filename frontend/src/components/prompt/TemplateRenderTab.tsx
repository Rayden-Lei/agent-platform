import { useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import { renderPromptTemplate, type PromptRenderResult, type PromptTemplateRow } from '../../api'
import { errorText } from '../../utils/errors'

// 渲染预览页签：按变量声明生成输入项，调后端渲染看结果；缺必填由后端 400 提示，不调模型。
// 页内片段，受控 state 自己管，不套弹窗。
interface Props { template: PromptTemplateRow }

export default function TemplateRenderTab({ template }: Props) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [result, setResult] = useState<PromptRenderResult | null>(null)
  const [rendering, setRendering] = useState(false)
  const render = async () => {
    setRendering(true)
    try { setResult(await renderPromptTemplate(template.id, values)) } catch (e) { toast.error(errorText(e, '渲染失败')) } finally { setRendering(false) }
  }
  const copy = () => {
    if (!result) return
    navigator.clipboard?.writeText(result.content).then(() => toast.success('已复制'))
  }
  return (
    <div className="flex flex-col gap-3">
      {template.variables.length ? template.variables.map((v) => (
        <div key={v.name} className="flex flex-col gap-1.5">
          <Label htmlFor={`render-var-${v.name}`} className="flex-wrap">
            <span className="font-medium">{v.name}</span>
            {v.required && !v.default && <span className="text-destructive">*</span>}
            {v.description && <span className="text-[12.5px] font-normal text-muted-foreground">（{v.description}）</span>}
          </Label>
          <Input
            id={`render-var-${v.name}`}
            value={values[v.name] ?? ''}
            placeholder={v.default ? '默认：' + v.default : ''}
            onChange={(e) => setValues({ ...values, [v.name]: e.target.value })}
          />
        </div>
      )) : (
        <div className="rounded-lg border border-border bg-secondary px-3 py-2 text-[13px] text-muted-foreground">该模板没有变量，直接渲染。</div>
      )}

      <div className="flex items-center gap-2">
        <Button variant="primary" size="sm" disabled={rendering} onClick={render}>{rendering ? '渲染中…' : '渲染'}</Button>
        {result && <Button size="sm" variant="secondary" onClick={copy}>复制结果</Button>}
      </div>

      {result && (
        <div className="flex flex-col gap-1.5">
          <pre className="m-0 whitespace-pre-wrap rounded-lg border border-border bg-secondary p-3 text-[13px] leading-relaxed text-foreground">{result.content}</pre>
          {result.unused.length > 0 && (
            <p className="m-0 flex flex-wrap items-center gap-1.5 text-[12.5px] text-muted-foreground">
              声明了但内容未使用：
              {result.unused.map((n) => <Badge key={n}>{n}</Badge>)}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
