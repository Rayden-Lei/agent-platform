import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/shadcn/dialog'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Switch } from '@/components/shadcn/switch'
import Button from '../ui/Button'
import { createKB, updateKB, type KnowledgeBaseInput, type KnowledgeBaseRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'

// 知识库新建 / 编辑弹窗：名称、描述、向量模型（建库后不可改）、切片参数（只影响之后上传的文档）。
// 访问权限只在新建时设初始值；之后在详情的"访问权限"页签改（docs/15 KB-01），编辑只提交名称、描述与切片参数。
interface Props {
  open: boolean
  editing: KnowledgeBaseRow | null
  onClose: () => void
  onSaved: (kb: KnowledgeBaseRow) => void
}

const EMPTY = {
  name: '',
  description: '',
  embedding_model: 'text-embedding-3-small',
  chunk_size: 500,
  chunk_overlap: 50,
  is_public: true,
  visible_roles: [] as string[],
}

export default function KbForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const roles = statusOptions('role')

  useEffect(() => {
    if (!open) return
    setError(null)
    setValues(editing
      ? {
          name: editing.name,
          description: editing.description ?? '',
          embedding_model: editing.embedding_model,
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
    // 服务端同样会校验，这里只是提前给出可读提示
    if (!values.name.trim()) { setError('请填写名称'); return }
    if (values.chunk_overlap >= values.chunk_size) { setError('切片重叠要小于切片大小'); return }
    setSubmitting(true)
    try {
      const { name, description, chunk_size, chunk_overlap } = values
      const payload: KnowledgeBaseInput = editing
        ? { name, description, chunk_size, chunk_overlap }
        : values
      const saved = editing ? await updateKB(editing.id, payload) : await createKB(payload)
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
            <Input id="kb-model" value={values.embedding_model} disabled={!!editing} onChange={(e) => set('embedding_model', e.target.value)} />
            <p className="m-0 text-[12px] text-muted-foreground">
              {editing ? '建库后不可更改；实际使用的向量后端以系统状态为准' : '记录用，实际向量后端由服务端 EMBEDDING_* 配置决定'}
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
