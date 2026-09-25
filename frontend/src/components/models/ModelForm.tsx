import { useEffect, useState } from 'react'
import { Divider, Form, Input, InputNumber, Modal, Select, message } from 'antd'
import { compactParams, createModel, updateModel, type ModelInput, type ModelRow } from '../../api'
import { statusOptions } from '../../constants/status'
import { errorText } from '../../utils/errors'
import ModelParamsFields from './ModelParamsFields'

// 模型新增 / 编辑弹窗：api_key 编辑时不回显，留空表示沿用；默认参数被引用它的智能体继承（智能体可逐项覆盖）；
// 价格用于运行成本快照（改单价不追溯历史运行）。
interface Props { open: boolean; editing: ModelRow | null; onClose: () => void; onSaved: () => void }

export default function ModelForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) form.setFieldsValue({ ...editing, api_key: '', default_params: editing.default_params ?? {} })
  }, [open, editing, form])

  const onSubmit = async (values: ModelInput) => {
    setSubmitting(true)
    try {
      // 默认参数只提交填了的键（后端只认 temperature / top_p / max_tokens / thinking，未知键 422）；选"跟随模型默认"即不设置
      const payload: ModelInput = { ...values, default_params: compactParams(values.default_params), api_key: values.api_key || undefined }
      if (editing) await updateModel(editing.id, payload)
      else await createModel({ ...payload, api_key: values.api_key })
      message.success('保存成功')
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑模型：${editing.name}` : '新增模型'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ provider: 'openai', api_key: '' }}>
        <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input /></Form.Item>
        <Form.Item name="provider" label="提供商" rules={[{ required: true }]}><Select options={statusOptions('provider')} /></Form.Item>
        <Form.Item name="api_base" label="API 地址" rules={[{ required: true, message: '请输入 API 地址' }]}><Input placeholder="https://xxx/v1" /></Form.Item>
        <Form.Item name="api_key" label="API Key" rules={[{ required: !editing, message: '请输入 API Key' }]} extra={editing ? '密钥不回显；留空则沿用已有密钥' : undefined}>
          <Input.Password placeholder={editing ? '留空则不修改' : '请输入 API Key'} autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="model_name" label="模型名" rules={[{ required: true, message: '请输入模型名' }]}><Input placeholder="deepseek-v4-pro-0813" /></Form.Item>
        <Divider style={{ margin: '4px 0 12px' }} plain>默认参数（引用它的智能体继承，可在智能体里逐项覆盖）</Divider>
        <Form.Item name={['default_params', 'thinking']} label="思考模式" extra="DeepSeek 等混合推理模型可关闭思考以大幅缩短首字节（实测 8.6 秒 → 3.1 秒），客服问答类建议关闭；不认识该参数的厂商保持「跟随模型默认」">
          <Select allowClear placeholder="跟随模型默认" options={statusOptions('thinking')} />
        </Form.Item>
        <ModelParamsFields name="default_params" />
        <div style={{ display: 'flex', gap: 12 }}>
          <Form.Item name="price_input" label="输入价格（元 / 百万 token）" style={{ flex: 1 }}><InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="可选" /></Form.Item>
          <Form.Item name="price_output" label="输出价格（元 / 百万 token）" style={{ flex: 1 }}><InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="可选" /></Form.Item>
        </div>
        <div style={{ fontSize: 12, color: '#9ca3af', marginTop: -8 }}>价格用于按运行快照计算成本；改价只影响之后的运行，历史成本不追溯。</div>
      </Form>
    </Modal>
  )
}
