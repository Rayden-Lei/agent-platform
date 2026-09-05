import { useEffect, useState } from 'react'
import { Form, Input, InputNumber, Modal, Select, message } from 'antd'
import { createTool, updateTool, type ToolConfig, type ToolInput, type ToolRow } from '../../api'
import { statusOptions } from '../../constants/status'
import ToolParamsEditor, { rowsFromSchema, schemaFromRows, type ParamRow } from './ToolParamsEditor'
import { errorText } from '../../utils/errors'

// 工具新增 / 编辑弹窗：HTTP 工具的方法 / 地址 / 请求头结构化录入，参数声明用表格；builtin 类型 config 恒为空对象。
interface Props { open: boolean; editing: ToolRow | null; onClose: () => void; onSaved: () => void }
interface FormValues { name: string; description: string; type: 'builtin' | 'http'; timeout: number; method?: string; url?: string; headersStr?: string; params?: ParamRow[] }
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => ({ value: m, label: m }))

export default function ToolForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) {
      const { parameters, url, method, headers } = editing.config || {}
      form.setFieldsValue({ name: editing.name, description: editing.description, type: editing.type, timeout: editing.timeout, method: (method || 'POST').toUpperCase(), url, headersStr: headers && Object.keys(headers).length ? JSON.stringify(headers, null, 2) : '', params: rowsFromSchema(parameters) })
    }
  }, [open, editing, form])

  const onSubmit = async (values: FormValues) => {
    let config: ToolConfig = {}
    if (values.type === 'http') {
      let headers: Record<string, string> = {}
      if (values.headersStr?.trim()) {
        try { headers = JSON.parse(values.headersStr) } catch { message.error('请求头 JSON 格式错误'); return }
        if (typeof headers !== 'object' || Array.isArray(headers)) { message.error('请求头必须是 JSON 对象'); return }
      }
      // 保留 config 里前端不认识的键（后端扩展字段），只覆盖结构化录入的四项
      const { parameters: _p, url: _u, method: _m, headers: _h, ...rest } = editing?.config || {}
      config = { ...rest, method: values.method, url: values.url, headers, parameters: schemaFromRows(values.params || []) }
    }
    const payload: ToolInput = { name: values.name, description: values.description, type: values.type, config, timeout: values.timeout }
    setSubmitting(true)
    try {
      if (editing) await updateTool(editing.id, payload)
      else await createTool(payload)
      message.success(editing ? '保存成功' : '创建成功')
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑工具：${editing.name}` : '新增工具'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden width={760}>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ type: 'builtin', timeout: 30, params: [], method: 'POST' }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]} extra="模型按名称选择工具，用英文标识更稳定"><Input /></Form.Item>
        <Form.Item name="description" label="描述" rules={[{ required: true }]} extra="模型据此判断何时调用，写清用途与输入输出"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="type" label="类型"><Select options={statusOptions('toolType')} disabled={!!editing} /></Form.Item>
        <Form.Item noStyle shouldUpdate={(a, b) => a.type !== b.type}>
          {({ getFieldValue }) => getFieldValue('type') === 'http' && (
            <>
              <div style={{ display: 'flex', gap: 12 }}>
                <Form.Item name="method" label="方法" style={{ width: 120 }}><Select options={METHODS} /></Form.Item>
                <Form.Item name="url" label="请求地址" style={{ flex: 1 }} rules={[{ required: true, message: '请输入请求地址' }, { type: 'url', message: '请输入合法的 URL' }]}><Input placeholder="https://api.example.com/v1/query" /></Form.Item>
              </div>
              <Form.Item name="headersStr" label="请求头（JSON 对象，可选）" extra="敏感值（如 Authorization）保存后在详情里不回显"><Input.TextArea rows={3} placeholder='{"Authorization": "Bearer ..."}' /></Form.Item>
              <Form.Item name="params" label="参数声明（模型按此以结构化参数调用）"><ToolParamsEditor /></Form.Item>
            </>
          )}
        </Form.Item>
        <Form.Item name="timeout" label="超时（秒）"><InputNumber min={1} max={300} /></Form.Item>
      </Form>
    </Modal>
  )
}
