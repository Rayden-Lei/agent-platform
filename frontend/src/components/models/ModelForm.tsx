import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { compactParams, createModel, updateModel, type ModelInput, type ModelParams, type ModelRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'
import ModelParamsFields from './ModelParamsFields'

// 模型新增 / 编辑：字段多（名称、提供商、地址、密钥、模型名、参数、价格）—— 用抽屉，不用弹窗。
// api_key 编辑时不回显，留空表示沿用；默认参数被引用它的智能体继承（智能体可逐项覆盖）；
// 价格用于运行成本快照（改单价不追溯历史运行）。
interface Props { open: boolean; editing: ModelRow | null; onClose: () => void; onSaved: () => void }

interface FormValues {
  name: string
  provider: string
  api_base: string
  api_key: string
  model_name: string
  thinking: '' | 'disabled' | 'enabled'
  params: ModelParams
  price_input: string
  price_output: string
}

type Errors = Partial<Record<keyof FormValues, string>>

const EMPTY: FormValues = {
  name: '', provider: 'openai', api_base: '', api_key: '', model_name: '',
  thinking: '', params: {}, price_input: '', price_output: '',
}

// 价格输入框留空表示未配置（null），不是 0：成本统计据此判断"无法计算"
const priceOf = (text: string): number | null => (text.trim() === '' ? null : Number(text))

export default function ModelForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [errors, setErrors] = useState<Errors>({})
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setErrors({})
    if (!editing) { setValues(EMPTY); return }
    const p = editing.default_params ?? {}
    setValues({
      name: editing.name,
      provider: editing.provider,
      api_base: editing.api_base,
      api_key: '',
      model_name: editing.model_name,
      thinking: p.thinking ?? '',
      params: { temperature: p.temperature ?? undefined, top_p: p.top_p ?? undefined, max_tokens: p.max_tokens ?? undefined },
      price_input: editing.price_input === null || editing.price_input === undefined ? '' : String(editing.price_input),
      price_output: editing.price_output === null || editing.price_output === undefined ? '' : String(editing.price_output),
    })
  }, [open, editing])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => {
    setValues((s) => ({ ...s, [key]: v }))
    setErrors((e) => (e[key] ? { ...e, [key]: undefined } : e))
  }

  const onSubmit = async () => {
    // 服务端同样会校验（未知参数键 422），这里只是提前给出可读提示
    const next: Errors = {}
    if (!values.name.trim()) next.name = '请输入名称'
    if (!values.api_base.trim()) next.api_base = '请输入 API 地址'
    if (!values.model_name.trim()) next.model_name = '请输入模型名'
    if (!editing && !values.api_key.trim()) next.api_key = '请输入 API Key'
    if (values.price_input.trim() && Number.isNaN(Number(values.price_input))) next.price_input = '请输入数字'
    if (values.price_output.trim() && Number.isNaN(Number(values.price_output))) next.price_output = '请输入数字'
    if (Object.keys(next).length) { setErrors(next); return }

    // 默认参数只提交填了的键（后端只认 temperature / top_p / max_tokens / thinking，未知键 422）；"跟随模型默认"即不设置
    const default_params: ModelParams = { ...compactParams(values.params), ...(values.thinking ? { thinking: values.thinking } : {}) }
    const payload: ModelInput = {
      name: values.name.trim(),
      provider: values.provider,
      api_base: values.api_base.trim(),
      model_name: values.model_name.trim(),
      default_params,
      price_input: priceOf(values.price_input),
      price_output: priceOf(values.price_output),
      api_key: values.api_key || undefined,
    }
    setSubmitting(true)
    try {
      if (editing) await updateModel(editing.id, payload)
      else await createModel({ ...payload, api_key: values.api_key.trim() })
      toast.success('保存成功')
      onSaved()
      onClose()
    } catch (e) {
      toast.error(errorText(e, '保存失败'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      title={editing ? `编辑模型：${editing.name}` : '新增模型'}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="model-name">名称</Label>
          <Input id="model-name" value={values.name} onChange={(e) => set('name', e.target.value)} placeholder="例如：DeepSeek 主力" aria-invalid={!!errors.name} />
          {errors.name && <p className="m-0 text-[12.5px] text-destructive">{errors.name}</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="model-provider">提供商</Label>
          <Select value={values.provider} onValueChange={(v) => set('provider', v)}>
            <SelectTrigger id="model-provider" className="h-9 w-full text-[13px]">
              <SelectValue placeholder="选择提供商" />
            </SelectTrigger>
            <SelectContent>
              {statusOptions('provider').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="model-base">API 地址</Label>
          <Input id="model-base" value={values.api_base} onChange={(e) => set('api_base', e.target.value)} placeholder="https://xxx/v1" aria-invalid={!!errors.api_base} />
          {errors.api_base && <p className="m-0 text-[12.5px] text-destructive">{errors.api_base}</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="model-key">API Key</Label>
          <Input
            id="model-key"
            type="password"
            autoComplete="new-password"
            value={values.api_key}
            onChange={(e) => set('api_key', e.target.value)}
            placeholder={editing ? '留空则不修改' : '请输入 API Key'}
            aria-invalid={!!errors.api_key}
          />
          {errors.api_key
            ? <p className="m-0 text-[12.5px] text-destructive">{errors.api_key}</p>
            : editing && <p className="m-0 text-[12px] text-muted-foreground">密钥不回显；留空则沿用已有密钥</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="model-model-name">模型名</Label>
          <Input id="model-model-name" value={values.model_name} onChange={(e) => set('model_name', e.target.value)} placeholder="deepseek-v4-pro-0813" aria-invalid={!!errors.model_name} />
          {errors.model_name && <p className="m-0 text-[12.5px] text-destructive">{errors.model_name}</p>}
        </div>

        <div className="flex flex-col gap-3.5 border-t border-border pt-3.5">
          <h3 className="m-0 text-[13px] font-medium text-foreground">默认参数（引用它的智能体继承，可在智能体里逐项覆盖）</h3>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="model-thinking">思考模式</Label>
            <Select value={values.thinking || 'inherit'} onValueChange={(v) => set('thinking', v === 'inherit' ? '' : (v as 'disabled' | 'enabled'))}>
              <SelectTrigger id="model-thinking" className="h-9 w-full text-[13px]">
                <SelectValue placeholder="跟随模型默认" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="inherit">跟随模型默认</SelectItem>
                {statusOptions('thinking').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
            <p className="m-0 text-[12px] text-muted-foreground">
              DeepSeek 等混合推理模型可关闭思考以大幅缩短首字节（实测 8.6 秒 → 3.1 秒），客服问答类建议关闭；不认识该参数的厂商保持「跟随模型默认」
            </p>
          </div>

          <ModelParamsFields value={values.params} onChange={(p) => set('params', p)} />

          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="model-price-in">输入价格（元 / 百万 token）</Label>
              <Input id="model-price-in" type="number" min={0} step={0.1} value={values.price_input} placeholder="可选" aria-invalid={!!errors.price_input} onChange={(e) => set('price_input', e.target.value)} />
              {errors.price_input && <p className="m-0 text-[12.5px] text-destructive">{errors.price_input}</p>}
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="model-price-out">输出价格（元 / 百万 token）</Label>
              <Input id="model-price-out" type="number" min={0} step={0.1} value={values.price_output} placeholder="可选" aria-invalid={!!errors.price_output} onChange={(e) => set('price_output', e.target.value)} />
              {errors.price_output && <p className="m-0 text-[12.5px] text-destructive">{errors.price_output}</p>}
            </div>
          </div>
          <p className="m-0 text-[12px] text-muted-foreground">价格用于按运行快照计算成本；改价只影响之后的运行，历史成本不追溯。</p>
        </div>
      </div>
    </Drawer>
  )
}
