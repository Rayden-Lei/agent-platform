import { useEffect, useState } from 'react'
import { Form, Input, Modal, Select, Typography, message } from 'antd'
import { createSchedule, listWorkflows, OPTIONS_PAGE, updateSchedule, type ScheduleRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import { errorText } from '../../utils/errors'

// 定时任务新建 / 编辑弹窗：工作流 + cron（5 段，服务端校验非法 422）+ 固定输入 JSON。
interface Props { open: boolean; editing: ScheduleRow | null; onClose: () => void; onSaved: () => void }
interface FormValues { name: string; workflow_id: number; cron: string; inputStr?: string }
const CRON_EXAMPLES = [['*/5 * * * *', '每 5 分钟'], ['0 * * * *', '每小时整点'], ['0 9 * * 1-5', '工作日 9:00'], ['30 2 1 * *', '每月 1 日 2:30']]

export default function ScheduleForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  const workflows = useAsyncData(() => listWorkflows(OPTIONS_PAGE), [], { auto: open, errorText: '加载工作流失败' })
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) form.setFieldsValue({ name: editing.name, workflow_id: editing.workflow_id, cron: editing.cron, inputStr: Object.keys(editing.input || {}).length ? JSON.stringify(editing.input, null, 2) : '' })
  }, [open, editing, form])

  const onSubmit = async (values: FormValues) => {
    let input: Record<string, unknown> = {}
    if (values.inputStr?.trim()) {
      try { input = JSON.parse(values.inputStr) } catch { message.error('输入 JSON 格式错误'); return }
      if (typeof input !== 'object' || Array.isArray(input)) { message.error('输入必须是 JSON 对象'); return }
    }
    const payload = { name: values.name, workflow_id: values.workflow_id, cron: values.cron.trim(), input }
    setSubmitting(true)
    try {
      if (editing) await updateSchedule(editing.id, payload)
      else await createSchedule(payload)
      message.success(editing ? '已保存' : '创建成功')
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑定时任务：${editing.name}` : '新建定时任务'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 128 }]}><Input /></Form.Item>
        <Form.Item name="workflow_id" label="工作流" rules={[{ required: true }]} extra={workflows.error || undefined}>
          <Select showSearch optionFilterProp="label" loading={workflows.loading} options={(workflows.data?.items ?? []).map((w) => ({ value: w.id, label: `${w.name}${w.status !== 'published' ? '（草稿）' : ''}` }))} />
        </Form.Item>
        <Form.Item name="cron" label="Cron 表达式（分 时 日 月 周，服务器时区）" rules={[{ required: true }, { pattern: /^\S+\s+\S+\s+\S+\s+\S+\s+\S+$/, message: '需要 5 段，用空格分隔' }]}>
          <Input placeholder="*/5 * * * *" style={{ fontFamily: 'monospace' }} />
        </Form.Item>
        <div style={{ marginTop: -12, marginBottom: 12 }}>
          {CRON_EXAMPLES.map(([expr, label]) => <Typography.Link key={expr} style={{ fontSize: 12, marginRight: 12 }} onClick={() => form.setFieldValue('cron', expr)}>{label} <code>{expr}</code></Typography.Link>)}
        </div>
        <Form.Item name="inputStr" label="固定输入（JSON 对象，可选）" extra="每次触发都以此作为工作流入参；运行记录里来源标为「定时任务」">
          <Input.TextArea rows={3} placeholder='{"input": "工作流输入"}' style={{ fontFamily: 'monospace' }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
