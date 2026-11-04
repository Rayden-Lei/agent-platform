import { CircleHelp } from 'lucide-react'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import type { ModelParams } from '../../api'

// 模型调用参数的三个输入框：模型表单填"默认参数"，智能体表单填"覆盖参数"（都通过 value / onChange 受控）。
// 用可清空的数字框而不是滑块：滑块拖过就清不掉，而"留空 = 继承上一层"是这组参数的核心语义。
// inherited 传所选模型的默认参数时，占位文字显示将继承的值。
interface Props {
  value?: ModelParams
  onChange?: (next: ModelParams) => void
  inherited?: ModelParams
}

const FIELDS = [
  { key: 'temperature', min: 0, max: 2, step: 0.1, hint: '0～2，越高越发散，0 最稳定' },
  { key: 'top_p', min: 0, max: 1, step: 0.05, hint: '0～1，核采样阈值；一般只调 temperature 与 top_p 之一' },
  { key: 'max_tokens', min: 1, max: 128000, step: 1, hint: '单次回答的最大 token 数，1～128000' },
] as const

export default function ModelParamsFields({ value, onChange, inherited }: Props) {
  const hint = (key: 'temperature' | 'top_p' | 'max_tokens') => {
    const v = inherited?.[key]
    if (v !== undefined && v !== null) return `继承模型默认 ${v}`
    return inherited ? '继承模型默认（未设置）' : '厂商默认'
  }

  // 留空即 undefined：提交时 compactParams 会把它去掉，表示"继承上一层"而不是显式 null
  const update = (key: 'temperature' | 'top_p' | 'max_tokens', text: string) => {
    const next: ModelParams = { ...(value ?? {}) }
    next[key] = text.trim() === '' ? undefined : Number(text)
    onChange?.(next)
  }

  return (
    <div className="flex flex-wrap gap-3">
      {FIELDS.map((f) => (
        <div key={f.key} className="flex min-w-[140px] flex-1 flex-col gap-1.5">
          <div className="flex items-center gap-1">
            <Label htmlFor={`param-${f.key}`} className="font-mono text-[12.5px]">{f.key}</Label>
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" className="text-muted-foreground" aria-label={`${f.key} 说明`}>
                  <CircleHelp className="size-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>{f.hint}</TooltipContent>
            </Tooltip>
          </div>
          <Input
            id={`param-${f.key}`}
            type="number"
            min={f.min}
            max={f.max}
            step={f.step}
            value={value?.[f.key] ?? ''}
            placeholder={hint(f.key)}
            onChange={(e) => update(f.key, e.target.value)}
            className="h-9 text-[13px]"
          />
        </div>
      ))}
    </div>
  )
}
