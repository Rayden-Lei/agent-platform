import type { ReactNode } from 'react'
import { Card, Form, Input, Select, Typography } from 'antd'
import type { FormInstance } from 'antd'
import { compactParams, type AgentDetail, type AgentInput, type ModelRow, type PromptRenderResult, type PromptTemplateRow } from '../../../api'
import AgentTemplateFields from '../../prompt/AgentTemplateFields'
import ModelParamsFields from '../../models/ModelParamsFields'

// 装配页左栏：五个分区卡片（锚点导航用 EDITOR_SECTIONS 的 key 定位）。整页共用一个 Form，由页面持有与提交。
// 第 2 批起追加"开场白""检索""对话设置"；"关联工作流（预留）"不再显示（docs/15 D-12），保存时原样带回。
export const EDITOR_SECTIONS = [
  { key: 'basic', title: '基础信息' }, { key: 'model', title: '模型与参数' }, { key: 'prompt', title: '提示词' },
  { key: 'kb', title: '知识库' }, { key: 'tools', title: '工具' },
]
export const sectionId = (key: string) => `agent-section-${key}`

export interface Option { value: number; label: string }
interface Props {
  form: FormInstance
  models: ModelRow[]
  kbOptions: Option[]
  toolOptions: Option[]
  templates: PromptTemplateRow[]
  onRenderTemplate: (templateId: number, variables: Record<string, string>) => Promise<PromptRenderResult>
}

// 这三类被引用对象不进发布快照，在各自页面改了立即影响线上（docs/15 3.2"不随发布固化的依赖"）
const liveHint = (what: string) => `${what}本身在${what}页的修改（含启停、删除）不经发布，立即影响线上。`

function Section({ id, title, hint, children }: { id: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <Card id={sectionId(id)} size="small" title={title} style={{ marginBottom: 12 }}>
      {hint && <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: -4 }}>{hint}</Typography.Paragraph>}
      {children}
    </Card>
  )
}

export default function ConfigSections({ form, models, kbOptions, toolOptions, templates, onRenderTemplate }: Props) {
  const modelId = Form.useWatch('model_id', form) // 参数占位文字显示所选模型的默认值
  const maxTwenty = { type: 'array' as const, max: 20, message: '最多 20 个' }
  return (
    <>
      <Section id="basic" title="基础信息">
        <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 128 }]}><Input /></Form.Item>
        <Form.Item name="description" label="描述" rules={[{ max: 2000 }]}><Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
      </Section>
      <Section id="model" title="模型与参数" hint={liveHint('模型')}>
        <Form.Item name="model_id" label="模型" rules={[{ required: true }]}>
          <Select showSearch optionFilterProp="label" options={models.map((m) => ({ value: m.id, label: m.is_enabled ? m.name : `${m.name}（已停用）`, disabled: !m.is_enabled }))} />
        </Form.Item>
        <ModelParamsFields name="params" inherited={models.find((m) => m.id === modelId)?.default_params ?? {}} />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>留空继承模型默认；不同厂商支持的取值范围不同。</Typography.Text>
      </Section>
      <Section id="prompt" title="提示词">
        <AgentTemplateFields form={form} templates={templates} onRender={onRenderTemplate} />
      </Section>
      <Section id="kb" title="知识库" hint={liveHint('知识库')}>
        <Form.Item name="kb_ids" label="检索的知识库" extra="对话时先检索这些知识库，再把片段注入提示词" rules={[maxTwenty]}>
          <Select mode="multiple" optionFilterProp="label" options={kbOptions} allowClear />
        </Form.Item>
      </Section>
      <Section id="tools" title="工具" hint={liveHint('工具')}>
        <Form.Item name="tool_ids" label="HTTP 工具" extra="内置的时间与计算器工具总是可用；这里绑定自定义 HTTP 工具" rules={[maxTwenty]}>
          <Select mode="multiple" optionFilterProp="label" options={toolOptions} allowClear />
        </Form.Item>
      </Section>
    </>
  )
}

// 草稿 → 表单值。workflow_id 没有表单项，放进表单仓库只为保存时原样带回（PUT 是整体覆盖）
export function toFormValues(a: AgentDetail) {
  return {
    name: a.name, description: a.description ?? '', system_prompt: a.system_prompt, model_id: a.model_id, params: a.params ?? {},
    kb_ids: a.kb_ids ?? [], tool_ids: a.tool_ids ?? [], workflow_id: a.workflow_id,
    use_template: !!a.prompt_template_id, prompt_template_id: a.prompt_template_id, prompt_variables: a.prompt_variables ?? {},
  }
}

// 表单值 → 保存请求。手填与模板二选一：用模板时 system_prompt 传空串由后端渲染；留空的参数键不提交（继承模型默认）
export function toPayload(values: Record<string, unknown>): AgentInput {
  const { use_template: useTemplate, ...rest } = values
  const base = rest as unknown as AgentInput
  const payload: AgentInput = useTemplate
    ? { ...base, system_prompt: '', prompt_variables: base.prompt_variables || {} }
    : { ...base, prompt_template_id: null, prompt_variables: {} }
  return { ...payload, params: compactParams(payload.params) }
}
