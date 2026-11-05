import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import VariableFormFields from '../workflows/VariableFormFields'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { createSchedule, getWorkflowParameters, listWorkflows, OPTIONS_PAGE, updateSchedule, type ScheduleRow, type WorkflowVariableDecl } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import { errorText } from '../../utils/errors'

// 定时任务新建 / 编辑弹窗：工作流 + cron（5 段，服务端校验非法 422）+ 固定输入 JSON。
// 只有 4 个字段，用弹窗；它是从定时任务详情抽屉里点「编辑」打开的，抽屉里不再叠抽屉（DEVELOPMENT_RULES 第 6 条）。
interface Props { open: boolean; editing: ScheduleRow | null; onClose: () => void; onSaved: () => void }
// input 就是运行入参字典（{变量名: 值}），与 POST /workflows/{id}/run 的 inputs 同一份结构；
// 表单按所选工作流开始节点的声明生成，不再让用户手写 JSON（docs/15 WF-04）
interface FormValues { name: string; workflow_id: number | null; cron: string; inputs: Record<string, unknown> }
const EMPTY: FormValues = { name: '', workflow_id: null, cron: '', inputs: {} }
const CRON_EXAMPLES = [['*/5 * * * *', '每 5 分钟'], ['0 * * * *', '每小时整点'], ['0 9 * * 1-5', '工作日 9:00'], ['30 2 1 * *', '每月 1 日 2:30']]
const CRON_PATTERN = /^\S+\s+\S+\s+\S+\s+\S+\s+\S+$/

export default function ScheduleForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [variables, setVariables] = useState<WorkflowVariableDecl[]>([])
  const [variablesError, setVariablesError] = useState<string | null>(null)
  const workflows = useAsyncData(() => listWorkflows(OPTIONS_PAGE), [], { auto: open, errorText: '加载工作流失败' })

  useEffect(() => {
    if (!open) return
    setError(null)
    setValues(editing
      ? {
          name: editing.name,
          workflow_id: editing.workflow_id,
          cron: editing.cron,
          inputs: { ...(editing.input || {}) },
        }
      : EMPTY)
  }, [open, editing])

  // 所选工作流的输入声明：换工作流就重新取，表单随之重建（旧工作流的字段不应留在新表单里）
  useEffect(() => {
    const wid = values.workflow_id
    setVariablesError(null)
    if (!wid) { setVariables([]); return }
    getWorkflowParameters(wid)
      .then((p) => setVariables(p.variables))
      .catch((e) => { setVariables([]); setVariablesError(errorText(e, '读取输入声明失败')) })
  }, [values.workflow_id])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  const onSubmit = async () => {
    // 提示文案与原来 antd 规则一致，不改口径
    if (!values.name.trim()) { setError('请输入名称'); return }
    if (!values.workflow_id) { setError('请选择工作流'); return }
    if (!values.cron.trim()) { setError('请输入 Cron 表达式'); return }
    if (!CRON_PATTERN.test(values.cron.trim())) { setError('需要 5 段，用空格分隔'); return }
    // 空串按未填处理：必填缺值由后端按声明判定（400 文案会说是哪个变量），前端不重复一套规则
    const input: Record<string, unknown> = {}
    Object.entries(values.inputs).forEach(([k, v]) => { if (v !== undefined && v !== '') input[k] = v })
    const payload = { name: values.name, workflow_id: values.workflow_id, cron: values.cron.trim(), input }
    setSubmitting(true)
    try {
      if (editing) await updateSchedule(editing.id, payload)
      else await createSchedule(payload)
      toast.success(editing ? '已保存' : '创建成功')
      onSaved()
      onClose()
    } catch (e) { toast.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal
      open={open}
      title={editing ? `编辑定时任务：${editing.name}` : '新建定时任务'}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <form className="flex flex-col gap-3.5" onSubmit={(e) => { e.preventDefault(); onSubmit() }}>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="schedule-name">名称</Label>
          <Input id="schedule-name" value={values.name} maxLength={128} onChange={(e) => set('name', e.target.value)} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="schedule-workflow">工作流</Label>
          <Select
            value={values.workflow_id ? String(values.workflow_id) : undefined}
            onValueChange={(v) => set('workflow_id', Number(v))}
            disabled={workflows.loading}
          >
            <SelectTrigger id="schedule-workflow" className="w-full">
              <SelectValue placeholder={workflows.loading ? '加载中…' : '选择工作流'} />
            </SelectTrigger>
            <SelectContent>
              {(workflows.data?.items ?? []).map((w) => (
                <SelectItem key={w.id} value={String(w.id)}>{w.name}{w.status !== 'published' ? '（草稿）' : ''}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {workflows.error && <p className="m-0 text-[12px] text-destructive">{workflows.error}</p>}
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="schedule-cron">Cron 表达式（分 时 日 月 周，服务器时区）</Label>
          <Input
            id="schedule-cron"
            value={values.cron}
            placeholder="*/5 * * * *"
            className="font-mono"
            onChange={(e) => set('cron', e.target.value)}
          />
          <div className="flex flex-wrap gap-x-3 gap-y-1">
            {CRON_EXAMPLES.map(([expr, label]) => (
              <button
                key={expr}
                type="button"
                className="text-[12px] text-primary hover:underline"
                onClick={() => set('cron', expr)}
              >
                {label} <code className="font-mono">{expr}</code>
              </button>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label>固定输入</Label>
          {variablesError ? (
            <p className="m-0 text-[12px] text-destructive">{variablesError}</p>
          ) : (
            <VariableFormFields
              variables={variables}
              values={values.inputs}
              onChange={(v) => set('inputs', v)}
              idPrefix="schedule"
            />
          )}
          <p className="m-0 text-[12px] text-muted-foreground">每次触发都以此作为工作流入参；运行记录里来源标为「定时任务」</p>
        </div>

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </form>
    </Modal>
  )
}
