import { useEffect, useState } from 'react'
import { Checkbox, Form, Input, InputNumber, Modal, Select, message } from 'antd'
import { createTool, updateTool, type ToolAuthType, type ToolConfig, type ToolInput, type ToolRow } from '../../api'
import { statusOptions } from '../../constants/status'
import ToolParamsEditor, { rowsFromSchema, schemaFromRows, type ParamRow } from './ToolParamsEditor'
import { errorText } from '../../utils/errors'

// 工具新增 / 编辑弹窗：HTTP 工具的方法 / 地址 / 请求头结构化录入，参数声明用表格；builtin 类型 config 恒为空对象。
// 凭据走"鉴权"区（docs/15 RS-06）：加密托管、保存后任何地方都不回显；编辑时留空表示沿用，勾选"清除"才删除。
interface Props { open: boolean; editing: ToolRow | null; onClose: () => void; onSaved: () => void }
interface FormValues {
  name: string; description: string; type: 'builtin' | 'http'; timeout: number; method?: string; url?: string; headersStr?: string; params?: ParamRow[]
  authType: ToolAuthType; authLocation?: 'header' | 'query'; authName?: string; secret?: string; clearSecret?: boolean
}
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map((m) => ({ value: m, label: m }))
const AUTH_TYPES = [
  { value: 'none', label: '不需要' }, { value: 'bearer', label: 'Bearer Token（Authorization 头）' },
  { value: 'api_key', label: 'API Key（自定义请求头或查询参数）' }, { value: 'basic', label: 'Basic（用户名:密码）' },
]

export default function ToolForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) {
      const { parameters, url, method, headers } = editing.config || {}
      form.setFieldsValue({
        name: editing.name, description: editing.description, type: editing.type, timeout: editing.timeout, method: (method || 'POST').toUpperCase(), url,
        headersStr: headers && Object.keys(headers).length ? JSON.stringify(headers, null, 2) : '', params: rowsFromSchema(parameters),
        authType: editing.auth?.type ?? 'none', authLocation: editing.auth?.location ?? undefined, authName: editing.auth?.name ?? undefined,
      })
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
    const authType = values.type === 'http' ? values.authType : 'none'
    const auth = authType === 'api_key' ? { type: authType, location: values.authLocation, name: values.authName } : { type: authType }
    const payload: ToolInput = {
      name: values.name, description: values.description, type: values.type, config, timeout: values.timeout, auth,
      // 切回"不需要"时隐藏的凭据框里可能还留着值，不发上去（服务端会以"没选鉴权方式却填了凭据"拒绝）
      ...(authType !== 'none' && values.secret ? { secret: values.secret } : {}), clear_secret: authType === 'none' || !!values.clearSecret,
    }
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
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ type: 'builtin', timeout: 30, params: [], method: 'POST', authType: 'none', authLocation: 'header' }}>
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
              <Form.Item name="headersStr" label="请求头（JSON 对象，可选）" extra="只放非敏感的请求头；Authorization、Token、Key 这类凭据在下方鉴权里配置（写进这里保存会被拒绝）"><Input.TextArea rows={3} placeholder='{"Content-Type": "application/json"}' /></Form.Item>
              <ToolAuthFields hasSecret={!!editing?.auth?.has_secret} />
              <Form.Item name="params" label="参数声明（模型按此以结构化参数调用）"><ToolParamsEditor /></Form.Item>
            </>
          )}
        </Form.Item>
        <Form.Item name="timeout" label="超时（秒）"><InputNumber min={1} max={300} /></Form.Item>
      </Form>
    </Modal>
  )
}

// 鉴权区：api_key 要选位置与参数名；凭据用密码框，已配置时留空表示沿用（服务端同样校验：选了方式却没有凭据 400）
function ToolAuthFields({ hasSecret }: { hasSecret: boolean }) {
  return (
    <>
      <Form.Item name="authType" label="鉴权"><Select options={AUTH_TYPES} /></Form.Item>
      <Form.Item noStyle shouldUpdate={(a, b) => a.authType !== b.authType}>
        {({ getFieldValue }) => getFieldValue('authType') !== 'none' && (
          <>
            {getFieldValue('authType') === 'api_key' && (
              <div style={{ display: 'flex', gap: 12 }}>
                <Form.Item name="authLocation" label="位置" style={{ width: 140 }}><Select options={[{ value: 'header', label: '请求头' }, { value: 'query', label: '查询参数' }]} /></Form.Item>
                <Form.Item name="authName" label="参数名" style={{ flex: 1 }} rules={[{ required: true, message: '请填写参数名' }]}><Input placeholder="X-API-Key" /></Form.Item>
              </div>
            )}
            <Form.Item name="secret" label="凭据" extra="加密保存，之后任何页面与接口都不回显；调用时按上面的方式带上"
              rules={hasSecret ? [] : [{ required: true, message: '请填写凭据' }]}>
              <Input.Password autoComplete="new-password" placeholder={hasSecret ? '已配置，留空不修改' : getFieldValue('authType') === 'basic' ? '用户名:密码' : '粘贴 Token / Key'} />
            </Form.Item>
            {hasSecret && <Form.Item name="clearSecret" valuePropName="checked"><Checkbox>清除已保存的凭据</Checkbox></Form.Item>}
          </>
        )}
      </Form.Item>
    </>
  )
}
