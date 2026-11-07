import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Switch } from '@/components/shadcn/switch'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { createEmbeddingModel, updateEmbeddingModel, type EmbeddingModelInput, type EmbeddingModelRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'

// 向量模型新增 / 编辑：字段比对话模型少（地址、密钥、模型名、维度、单请求条数），但仍用抽屉保持一致。
// 维度必须与切片表向量列宽一致（服务端 422）：pgvector 是定长列，维度对不上入库必失败，
// 所以这里把要求值直接写进提示，别让人存完才知道。
interface Props {
  open: boolean
  editing: EmbeddingModelRow | null
  /** 切片表当前的向量列宽（来自系统状态里的 embedding.dim），用于表单预填与提示 */
  requiredDim: number
  onClose: () => void
  onSaved: () => void
}

interface FormValues {
  name: string
  provider: string
  api_base: string
  api_key: string
  model_name: string
  dim: string
  request_size: string
  is_enabled: boolean
}

type Errors = Partial<Record<keyof FormValues, string>>

const EMPTY: FormValues = {
  name: '', provider: 'openai', api_base: '', api_key: '', model_name: '',
  dim: '', request_size: '20', is_enabled: true,
}

export default function EmbeddingModelForm({ open, editing, requiredDim, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [errors, setErrors] = useState<Errors>({})
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    setErrors({})
    if (!editing) {
      setValues({ ...EMPTY, dim: String(requiredDim) })
      return
    }
    setValues({
      name: editing.name,
      provider: editing.provider,
      api_base: editing.api_base,
      api_key: '',
      model_name: editing.model_name,
      dim: String(editing.dim),
      request_size: String(editing.request_size),
      is_enabled: editing.is_enabled,
    })
  }, [open, editing, requiredDim])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => {
    setValues((s) => ({ ...s, [key]: v }))
    setErrors((e) => (e[key] ? { ...e, [key]: undefined } : e))
  }

  const onSubmit = async () => {
    // 服务端同样会校验；这里提前给出可读提示，避免白转一圈
    const next: Errors = {}
    if (!values.name.trim()) next.name = '请输入名称'
    if (!values.api_base.trim()) next.api_base = '请输入 API 地址'
    if (!values.model_name.trim()) next.model_name = '请输入模型名'
    if (!editing && !values.api_key.trim()) next.api_key = '请输入 API Key'
    const dim = Number(values.dim)
    if (!values.dim.trim() || Number.isNaN(dim)) next.dim = '请输入数字'
    else if (dim !== requiredDim) next.dim = `必须是 ${requiredDim}：切片表向量列宽是定长的，维度不一致无法入库`
    const size = Number(values.request_size)
    if (!values.request_size.trim() || Number.isNaN(size) || size < 1 || size > 500) next.request_size = '取值 1～500'
    if (Object.keys(next).length) { setErrors(next); return }

    const payload: EmbeddingModelInput = {
      name: values.name.trim(),
      provider: values.provider,
      api_base: values.api_base.trim(),
      model_name: values.model_name.trim(),
      dim,
      request_size: size,
      is_enabled: values.is_enabled,
      // 编辑时留空表示沿用已有密钥
      api_key: values.api_key.trim() || undefined,
    }
    setSubmitting(true)
    try {
      if (editing) await updateEmbeddingModel(editing.id, payload)
      else await createEmbeddingModel({ ...payload, api_key: values.api_key.trim() })
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
      width={680}
      title={editing ? `编辑向量模型：${editing.name}` : '新增向量模型'}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emb-name">名称</Label>
          <Input id="emb-name" value={values.name} onChange={(e) => set('name', e.target.value)} placeholder="例如：Cloudflare Qwen3 Embedding" aria-invalid={!!errors.name} />
          {errors.name && <p className="m-0 text-[12.5px] text-destructive">{errors.name}</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emb-provider">服务商</Label>
          <Select value={values.provider} onValueChange={(v) => set('provider', v)}>
            <SelectTrigger id="emb-provider" className="h-9 w-full text-[13px]">
              <SelectValue placeholder="选择服务商" />
            </SelectTrigger>
            <SelectContent>
              {statusOptions('provider').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emb-base">API 地址</Label>
          <Input id="emb-base" value={values.api_base} onChange={(e) => set('api_base', e.target.value)} placeholder="https://xxx/v1（要能接 OpenAI 兼容的 /embeddings）" aria-invalid={!!errors.api_base} />
          {errors.api_base && <p className="m-0 text-[12.5px] text-destructive">{errors.api_base}</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emb-key">API Key</Label>
          <Input
            id="emb-key"
            type="password"
            autoComplete="new-password"
            value={values.api_key}
            onChange={(e) => set('api_key', e.target.value)}
            placeholder={editing ? '留空则不修改' : '请输入 API Key'}
            aria-invalid={!!errors.api_key}
          />
          {errors.api_key
            ? <p className="m-0 text-[12.5px] text-destructive">{errors.api_key}</p>
            : <p className="m-0 text-[12px] text-muted-foreground">{editing ? '密钥不回显；留空则沿用已有密钥' : '加密存储，保存后任何接口都不再回显'}</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="emb-model">模型名</Label>
          <Input id="emb-model" value={values.model_name} onChange={(e) => set('model_name', e.target.value)} placeholder="@cf/qwen/qwen3-embedding-0.6b" aria-invalid={!!errors.model_name} />
          {errors.model_name && <p className="m-0 text-[12.5px] text-destructive">{errors.model_name}</p>}
        </div>

        <div className="flex gap-3">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="emb-dim">向量维度</Label>
            <Input id="emb-dim" type="number" min={1} max={4096} value={values.dim} onChange={(e) => set('dim', e.target.value)} aria-invalid={!!errors.dim} />
            {errors.dim
              ? <p className="m-0 text-[12.5px] text-destructive">{errors.dim}</p>
              : <p className="m-0 text-[12px] text-muted-foreground">必须等于切片表列宽 {requiredDim}（定长列，装不下别的维度）</p>}
          </div>
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="emb-size">单次请求条数</Label>
            <Input id="emb-size" type="number" min={1} max={500} value={values.request_size} onChange={(e) => set('request_size', e.target.value)} aria-invalid={!!errors.request_size} />
            {errors.request_size
              ? <p className="m-0 text-[12.5px] text-destructive">{errors.request_size}</p>
              : <p className="m-0 text-[12px] text-muted-foreground">服务商的单次上限（阿里云百炼 20，本地 oMLX 可更大）</p>}
          </div>
        </div>

        <div className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="emb-enabled" className="text-[13px] leading-none">启用</Label>
            <p className="m-0 text-[12px] leading-snug text-muted-foreground">停用后不会出现在建库下拉里；被知识库绑定的模型不能停用</p>
          </div>
          <Switch id="emb-enabled" checked={values.is_enabled} onCheckedChange={(v) => set('is_enabled', v)} />
        </div>

        <p className="m-0 text-[12px] text-muted-foreground">
          保存后建议点一次「测试」：它会真的发一条 embeddings 请求并核对返回维度。
        </p>
      </div>
    </Drawer>
  )
}
