import { useEffect, useState } from 'react'
import { Form, Input, Modal, Select, message } from 'antd'
import { createAgent, listKBs, listModels, listPromptTemplates, listTools, listWorkflows, OPTIONS_PAGE, updateAgent, type AgentInput, type AgentRow, type PromptTemplateRow } from '../../api'
import { errorText } from '../../utils/errors'
import AgentTemplateFields from '../prompt/AgentTemplateFields'
import AgentParamsFields from './AgentParamsFields'

// 智能体新增 / 编辑弹窗：名称、描述、提示词（手填或从模板生成）、模型、工具、知识库、工作流、高级参数。
// 下拉选项各取前 100 条；提交时手填与模板二选一（模板 → system_prompt 传空串由后端渲染）。
interface Props {
  open: boolean
  editing: AgentRow | null
  onClose: () => void
  onSaved: () => void
}

interface Option { value: number; label: string }

export default function AgentForm({ open, editing, onClose, onSaved }: Props) {
  const [form] = Form.useForm()
  const [models, setModels] = useState<Option[]>([])
  const [tools, setTools] = useState<Option[]>([])
  const [kbs, setKBs] = useState<Option[]>([])
  const [workflows, setWorkflows] = useState<Option[]>([])
  const [templates, setTemplates] = useState<PromptTemplateRow[]>([])
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!open) return
    Promise.all([listModels(OPTIONS_PAGE), listTools(OPTIONS_PAGE), listKBs(OPTIONS_PAGE), listWorkflows(OPTIONS_PAGE), listPromptTemplates(OPTIONS_PAGE)])
      .then(([m, t, k, w, p]) => {
        setModels(m.items.map((x) => ({ value: x.id, label: x.is_enabled ? x.name : `${x.name}（已停用）` })))
        setTools(t.items.map((x) => ({ value: x.id, label: x.is_enabled ? x.name : `${x.name}（已停用）` })))
        setKBs(k.items.map((x) => ({ value: x.id, label: x.name })))
        setWorkflows(w.items.map((x) => ({ value: x.id, label: x.name })))
        setTemplates(p.items)
      })
      .catch((e) => message.error(errorText(e, '加载选项失败')))
    form.resetFields()
    if (editing) form.setFieldsValue({ ...editing, use_template: !!editing.prompt_template_id })
  }, [open, editing, form])

  const onSubmit = async (values: Record<string, unknown>) => {
    const { use_template, ...rest } = values
    const base = rest as unknown as AgentInput
    const payload: AgentInput = use_template
      ? { ...base, system_prompt: '', prompt_template_id: base.prompt_template_id, prompt_variables: base.prompt_variables || {} }
      : { ...base, prompt_template_id: null, prompt_variables: {} }
    // 高级参数留空的键不提交，避免把 undefined / null 透传给模型
    payload.params = Object.fromEntries(Object.entries(payload.params || {}).filter(([, v]) => v !== undefined && v !== null))
    setSubmitting(true)
    try {
      if (editing) await updateAgent(editing.id, payload)
      else await createAgent(payload)
      message.success('保存成功')
      onSaved()
      onClose()
    } catch (e) {
      message.error(errorText(e, '保存失败'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal title={editing ? `编辑智能体：${editing.name}` : '新增智能体'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} width={680} destroyOnClose>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ use_template: false, params: {} }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="description" label="描述"><Input /></Form.Item>
        <AgentTemplateFields form={form} templates={templates} />
        <Form.Item name="model_id" label="模型" rules={[{ required: true }]}>
          <Select showSearch optionFilterProp="label" options={models} />
        </Form.Item>
        <Form.Item name="tool_ids" label="工具" extra="内置的时间与计算器工具总是可用；这里绑定自定义 HTTP 工具">
          <Select mode="multiple" optionFilterProp="label" options={tools} allowClear />
        </Form.Item>
        <Form.Item name="kb_ids" label="知识库" extra="对话时先检索这些知识库，再把片段注入提示词">
          <Select mode="multiple" optionFilterProp="label" options={kbs} allowClear />
        </Form.Item>
        <Form.Item name="workflow_id" label="关联工作流（预留）">
          <Select allowClear showSearch optionFilterProp="label" options={workflows} placeholder="当前对话不使用" />
        </Form.Item>
        <AgentParamsFields />
      </Form>
    </Modal>
  )
}
