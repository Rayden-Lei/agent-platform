import { useEffect, useState } from 'react'
import { Form, Input, InputNumber, Modal, message } from 'antd'
import { createApiKey, updateApiKey, type ApiKeyInput, type ApiKeyRow } from '../../api'
import { errorText } from '../../utils/errors'

// API Key 生成 / 编辑弹窗：白名单用多行文本承载（一行一条），提交前拆成数组；CIDR 与范围合法性由服务端 422 兜底。
interface Props { open: boolean; editing: ApiKeyRow | null; onClose: () => void; onSaved: () => void; onCreated: (key: string) => void }
interface FormValues { name: string; quota: number; allowed_ips_text?: string; rate_limit_per_minute: number }
const splitIps = (text?: string): string[] => (text ?? '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean)

export default function ApiKeyForm({ open, editing, onClose, onSaved, onCreated }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) form.setFieldsValue({ name: editing.name, quota: editing.quota, allowed_ips_text: editing.allowed_ips.join('\n'), rate_limit_per_minute: editing.rate_limit_per_minute })
  }, [open, editing, form])

  const onSubmit = async (values: FormValues) => {
    const payload: ApiKeyInput = { name: values.name, quota: values.quota ?? 1000, allowed_ips: splitIps(values.allowed_ips_text), rate_limit_per_minute: values.rate_limit_per_minute ?? 0 }
    setSubmitting(true)
    try {
      if (editing) { await updateApiKey(editing.id, payload); message.success('已保存') } else { const res = await createApiKey(payload); onCreated(res.key) }
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, editing ? '保存失败' : '创建失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑 API Key：${editing.name}` : '生成 API Key'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ quota: 1000, rate_limit_per_minute: 0 }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 64 }]}><Input placeholder="如：生产环境调用" /></Form.Item>
        <Form.Item name="quota" label="配额（调用次数）" rules={[{ required: true }]} extra="每次成功进入业务接口的请求消耗 1 次；用完后 403，编辑配额可续">
          <InputNumber min={0} style={{ width: '100%' }} />
        </Form.Item>
        <Form.Item name="allowed_ips_text" label="允许的来源 IP（一行一条，IP 或 CIDR；留空不限制）" extra="不在名单内的来源会被拒绝（403）且不扣配额。最多 50 条。">
          <Input.TextArea rows={3} placeholder={'10.20.0.0/16\n203.0.113.8'} style={{ fontFamily: 'monospace' }} />
        </Form.Item>
        <Form.Item name="rate_limit_per_minute" label="每分钟限速" extra="0 表示使用服务端全局默认；超限返回 429 且不扣配额。">
          <InputNumber min={0} max={10000} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  )
}
