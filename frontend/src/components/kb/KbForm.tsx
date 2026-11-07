import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/shadcn/dialog'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Switch } from '@/components/shadcn/switch'
import Button from '../ui/Button'
import { createKB, listEmbeddingModelOptions, updateKB, type EmbeddingModelOption, type KnowledgeBaseInput, type KnowledgeBaseRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'

// 知识库新建 / 编辑弹窗：名称、描述、向量模型（下拉选一个真实模型，建库后不可改）、切片参数（只影响之后上传的文档）。
// 访问权限只在新建时设初始值；之后在详情的"访问权限"页签改（docs/15 KB-01），编辑只提交名称、描述与切片参数。
//
// 向量模型 2026-11-08 起是下拉：此前是自由文本输入框，只落库不生效，默认值还是个本平台没有的模型名，
// 建完库看到的名字和实际用的模型是两回事。现在入库与检索都真的按选中的模型走。
interface Props {
  open: boolean
  editing: KnowledgeBaseRow | null
  onClose: () => void
  onSaved: (kb: KnowledgeBaseRow) => void
}

const EMPTY = {
  name: '',
  description: '',
  embedding_model_id: '',
  chunk_size: 500,
  chunk_overlap: 50,
  is_public: true,
  visible_roles: [] as string[],
}

export default function KbForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [models, setModels] = useState<EmbeddingModelOption[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const roles = statusOptions('role')

  // 候选只在新建时拉：编辑态这个字段是只读的（建库后不可改），不必请求
  useEffect(() => {
    if (!open || editing) return
    setModelsLoading(true)
    listEmbeddingModelOptions()
      .then((r) => {
        setModels(r.items)
        // 只有一个可选模型时直接选中，省一次点击；多个时留空强制人选，避免默认绑错
        if (r.items.length === 1) setValues((s) => (s.embedding_model_id ? s : { ...s, embedding_model_id: String(r.items[0].id) }))
      })
      .catch((e) => setError(errorText(e, '加载向量模型失败')))
      .finally(() => setModelsLoading(false))
  }, [open, editing])

  useEffect(() => {
    if (!open) return
    setError(null)
    setValues(editing
      ? {
          name: editing.name,
          description: editing.description ?? '',
          embedding_model_id: String(editing.embedding_model_id),
          chunk_size: editing.chunk_size,
          chunk_overlap: editing.chunk_overlap,
          is_public: editing.is_public,
          visible_roles: editing.visible_roles || [],
        }
      : EMPTY)
  }, [open, editing])

  const set = <K extends keyof typeof EMPTY>(key: K, v: (typeof EMPTY)[K]) => setValues((s) => ({ ...s, [key]: v }))

  const toggleRole = (role: string) => setValues((s) => ({
    ...s,
    visible_roles: s.visible_roles.includes(role) ? s.visible_roles.filter((r) => r !== role) : [...s.visible_roles, role],
  }))

  const onSubmit = async () => {
    // 服务端同样会校验（名称长度、切片范围、模型是否存在且启用），这里只是提前给出可读提示
    if (!values.name.trim()) { setError('请填写名称'); return }
    if (!editing && !values.embedding_model_id) { setError('请选择向量模型'); return }
    if (values.chunk_overlap >= values.chunk_size) { setError('切片重叠要小于切片大小'); return }
    setSubmitting(true)
    try {
      const { name, description, chunk_size, chunk_overlap } = values
      const payload: KnowledgeBaseInput = editing
        ? { name, description, chunk_size, chunk_overlap, embedding_model_id: Number(values.embedding_model_id) }
        : { ...values, embedding_model_id: Number(values.embedding_model_id) }
      // 编辑只改这四项（多带字段服务端 422）；embedding_model_id 服务端不接收，带上只为满足类型
      const saved = editing
        ? await updateKB(editing.id, { name, description, chunk_size, chunk_overlap })
        : await createKB(payload)
      toast.success(editing ? '已保存' : '创建成功')
      onSaved(saved)
      onClose()
    } catch (e) {
      setError(errorText(e, '保存失败'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => { if (!next) onClose() }}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? `编辑知识库：${editing.name}` : '新建知识库'}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3.5">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="kb-name">名称</Label>
            <Input id="kb-name" value={values.name} onChange={(e) => set('name', e.target.value)} placeholder="例如：产品手册" />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="kb-desc">描述</Label>
            <Input id="kb-desc" value={values.description} onChange={(e) => set('description', e.target.value)} placeholder="这个库收录什么内容" />
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="kb-model">向量模型</Label>
            {editing ? (
              // 建库后不可改：换了向量模型等于换了向量空间，已有切片全部作废
              <Input id="kb-model" value={editing.embedding_model ? `${editing.embedding_model.name}（${editing.embedding_model.dim} 维）` : '模型已删除'} disabled />
            ) : (
              <Select value={values.embedding_model_id} onValueChange={(v) => set('embedding_model_id', v)} disabled={modelsLoading || models.length === 0}>
                <SelectTrigger id="kb-model" className="h-9 w-full text-[13px]">
                  <SelectValue placeholder={modelsLoading ? '加载中…' : models.length ? '选择一个向量模型' : '还没有可用的向量模型'} />
                </SelectTrigger>
                <SelectContent>
                  {models.map((m) => (
                    <SelectItem key={m.id} value={String(m.id)}>{m.name}（{m.dim} 维）</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            <p className="m-0 text-[12px] text-muted-foreground">
              {editing
                ? '建库后不可更改：换了模型等于换了向量空间，已有切片会全部作废'
                : models.length
                  ? '文档入库与检索都按这个模型走，建库后不可更改。候选来自「向量模型」页面'
                  : '还没有启用的向量模型，先到「向量模型」页面添加一个，再回来建库'}
            </p>
          </div>

          <div className="flex gap-3">
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="kb-size">切片大小（字符）</Label>
              <Input id="kb-size" type="number" min={50} max={5000} value={values.chunk_size} onChange={(e) => set('chunk_size', Number(e.target.value))} />
            </div>
            {/* 重叠不小于切片大小时切分会原地打转；服务端同样拦（422），这里提前提示 */}
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="kb-overlap">切片重叠</Label>
              <Input id="kb-overlap" type="number" min={0} max={1000} value={values.chunk_overlap} onChange={(e) => set('chunk_overlap', Number(e.target.value))} />
            </div>
          </div>

          {editing ? (
            <p className="m-0 text-[12px] text-muted-foreground">切片参数只影响之后上传的文档；已有文档可在详情页"重新解析"按新参数重建。访问权限在详情页的"访问权限"页签修改。</p>
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="kb-public" className="text-[13px] leading-none">公开（所有角色可见）</Label>
                  <p className="m-0 text-[12px] leading-snug text-muted-foreground">关闭后只有下面勾选的角色能检索</p>
                </div>
                <Switch id="kb-public" checked={values.is_public} onCheckedChange={(v) => set('is_public', v)} />
              </div>
              {!values.is_public && (
                <div className="flex flex-col gap-1.5">
                  <Label>可见角色（非公开时生效）</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {roles.map((r) => {
                      const on = values.visible_roles.includes(r.value)
                      return (
                        <Button
                          key={r.value}
                          size="sm"
                          variant={on ? 'primary' : 'secondary'}
                          onClick={() => toggleRole(r.value)}
                        >
                          {r.label}
                        </Button>
                      )
                    })}
                  </div>
                  <p className="m-0 text-[12px] text-muted-foreground">建好后可在详情页的"访问权限"页签修改；管理员始终可见</p>
                </div>
              )}
            </>
          )}

          {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
