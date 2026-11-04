import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { createPromptTemplate, updatePromptTemplate, type PromptTemplateInput, type PromptTemplateRow } from '../../api'
import VariablesEditor, { rowsFromVariables, variablesFromRows, type VarRow } from './VariablesEditor'
import { errorText } from '../../utils/errors'

// 模板新增 / 编辑：字段多、正文长、还带一张变量表 —— 用抽屉（整高、正文滚动、按钮常驻），不用弹窗。
// 内容里用 {{变量名}} 引用变量；引用未声明的变量后端 400，声明了没用到的保存后提示。
interface Props { open: boolean; editing: PromptTemplateRow | null; onClose: () => void; onSaved: () => void }
interface FormValues { name: string; description?: string; content: string; variables: VarRow[] }

export default function TemplateForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>({ name: '', description: '', content: '', variables: [] })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    setError(null)
    setValues(editing
      ? { name: editing.name, description: editing.description || '', content: editing.content || '', variables: rowsFromVariables(editing.variables) }
      : { name: '', description: '', content: '', variables: [] })
  }, [open, editing])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  const onSubmit = async () => {
    if (!values.name.trim()) { setError('请填写名称'); return }
    if (!values.content.trim()) { setError('请填写内容'); return }
    const payload: PromptTemplateInput = {
      name: values.name.trim(),
      description: values.description || '',
      content: values.content,
      variables: variablesFromRows(values.variables || []),
    }
    setSubmitting(true)
    try {
      const saved = editing ? await updatePromptTemplate(editing.id, payload) : await createPromptTemplate(payload)
      if (saved.unused_variables?.length) toast.warning('已保存，但这些变量声明了却没在内容里使用：' + saved.unused_variables.join(', '))
      else toast.success(editing ? '保存成功' : '创建成功')
      onSaved()
      onClose()
    } catch (e) {
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
      title={editing ? `编辑模板：${editing.name}（当前 v${editing.version}）` : '新增模板'}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tpl-name">名称</Label>
          <Input id="tpl-name" value={values.name} maxLength={128} onChange={(e) => set('name', e.target.value)} placeholder="例如：客服助手系统提示词" />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tpl-desc">描述</Label>
          <Input id="tpl-desc" value={values.description} onChange={(e) => set('description', e.target.value)} placeholder="这个模板用在什么场景" />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tpl-content">内容</Label>
          <textarea
            id="tpl-content"
            rows={10}
            value={values.content}
            onChange={(e) => set('content', e.target.value)}
            placeholder={'你是{{role}}，请用{{tone}}的语气回答。'}
            className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <p className="m-0 text-[12px] text-muted-foreground">用 {'{{变量名}}'} 引用下方声明的变量；内容或变量变化会自动升版本，绑定的智能体重新保存草稿并发布后才用到新版</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label>变量声明（最多 30 个）</Label>
          <VariablesEditor value={values.variables} onChange={(rows) => set('variables', rows)} />
        </div>

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </div>
    </Drawer>
  )
}
