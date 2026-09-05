import { useEffect, useState } from 'react'
import { Form, Input, Modal, message } from 'antd'
import { createPromptTemplate, updatePromptTemplate, type PromptTemplateInput, type PromptTemplateRow } from '../../api'
import VariablesEditor, { rowsFromVariables, variablesFromRows, type VarRow } from './VariablesEditor'
import { errorText } from '../../utils/errors'

// 模板新增 / 编辑弹窗：内容里用 {{变量名}} 引用变量；引用未声明的变量后端 400，声明了没用到的保存后提示。
// editing 需要带 content（列表不下发，调用方先取详情）。
interface Props { open: boolean; editing: PromptTemplateRow | null; onClose: () => void; onSaved: () => void }
interface FormValues { name: string; description?: string; content: string; variables: VarRow[] }

export default function TemplateForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (editing) form.setFieldsValue({ name: editing.name, description: editing.description || '', content: editing.content || '', variables: rowsFromVariables(editing.variables) })
  }, [open, editing, form])

  const onSubmit = async (values: FormValues) => {
    const payload: PromptTemplateInput = { name: values.name, description: values.description || '', content: values.content, variables: variablesFromRows(values.variables || []) }
    setSubmitting(true)
    try {
      const saved = editing ? await updatePromptTemplate(editing.id, payload) : await createPromptTemplate(payload)
      if (saved.unused_variables?.length) message.warning('已保存，但这些变量声明了却没在内容里使用：' + saved.unused_variables.join(', '))
      else message.success(editing ? '保存成功' : '创建成功')
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑模板：${editing.name}（当前 v${editing.version}）` : '新增模板'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden width={800}>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ variables: [] }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 128 }]}><Input /></Form.Item>
        <Form.Item name="description" label="描述"><Input /></Form.Item>
        <Form.Item name="content" label="内容" rules={[{ required: true }]} extra="用 {{变量名}} 引用下方声明的变量；内容或变量变化会自动升版本，绑定的智能体需重新发布才用到新版">
          <Input.TextArea rows={10} placeholder={'你是{{role}}，请用{{tone}}的语气回答。'} />
        </Form.Item>
        <Form.Item name="variables" label="变量声明（最多 30 个）"><VariablesEditor /></Form.Item>
      </Form>
    </Modal>
  )
}
