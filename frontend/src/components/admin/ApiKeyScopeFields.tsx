import { Alert, Form, Select } from 'antd'
import type { FormInstance } from 'antd'
import type { ApiKeyRow, ApiKeyScopeItem } from '../../api'
import type { ScopeOptions } from '../../hooks/useApiKeyScopeOptions'

// API Key 表单的"授权范围"（docs/15 3.7.1）：可调用的智能体 / 工作流 / 检索放行的知识库，至少一项（服务端同样 400）。
// 预检：作用域内的智能体绑定了非公开、又没授权给这个 Key 的库时提示"对该 Key 检索不到"——Key 对话的检索只放行公开库与授权的库，
// 归属人是管理员也不例外。按智能体草稿的绑定估算（对话用的是线上版本，发布前后可能不同）。数据由页面传入，本组件不发请求。
interface Props { form: FormInstance; options: ScopeOptions; editing: ApiKeyRow | null }

type Option = { value: number; label: string }

// 已授权、但不在下拉第一页或已删除的资源也要能显示名字（否则只剩一个数字）
function withCurrent(listed: { id: number; name: string }[], current: ApiKeyScopeItem[] = []): Option[] {
  const seen = new Set(listed.map((x) => x.id))
  return [...listed.map((x) => ({ value: x.id, label: x.name })),
    ...current.filter((x) => !seen.has(x.id)).map((x) => ({ value: x.id, label: x.name ?? `已删除 #${x.id}` }))]
}

const atLeastOne = ({ getFieldValue }: FormInstance) => ({
  validator: () => (['agent_ids', 'workflow_ids', 'kb_ids'].some((f) => (getFieldValue(f) ?? []).length)
    ? Promise.resolve() : Promise.reject(new Error('至少授权一个智能体、工作流或知识库'))),
})

export default function ApiKeyScopeFields({ form, options, editing }: Props) {
  const agentIds: number[] = Form.useWatch('agent_ids', form) ?? []
  const kbIds: number[] = Form.useWatch('kb_ids', form) ?? []
  const kbById = new Map(options.kbs.map((k) => [k.id, k]))
  const blind = [...new Set(options.agents.filter((a) => agentIds.includes(a.id)).flatMap((a) => a.kb_ids))]
    .filter((id) => !kbIds.includes(id) && kbById.get(id)?.is_public === false)
    .map((id) => kbById.get(id)?.name ?? `#${id}`)
  const common = { mode: 'multiple' as const, optionFilterProp: 'label', allowClear: true, loading: options.loading, style: { width: '100%' } }

  return (
    <>
      {options.error && <Alert type="error" showIcon style={{ marginBottom: 12 }} message={options.error} />}
      <Form.Item name="agent_ids" label="可调用的智能体" dependencies={['workflow_ids', 'kb_ids']} rules={[atLeastOne]} extra="只能对话这里列出的智能体（未发布的调用时仍会被拒）">
        <Select {...common} placeholder="选择智能体" options={withCurrent(options.agents, editing?.scope.agents)} />
      </Form.Item>
      <Form.Item name="workflow_ids" label="可运行的工作流" dependencies={['agent_ids', 'kb_ids']} rules={[atLeastOne]} extra="运行与续跑都只限这里；续跑只能续本 Key 发起的运行">
        <Select {...common} placeholder="选择工作流" options={withCurrent(options.workflows, editing?.scope.workflows)} />
      </Form.Item>
      <Form.Item name="kb_ids" label="检索放行的非公开知识库" dependencies={['agent_ids', 'workflow_ids']} rules={[atLeastOne]} extra="对话检索只放行公开库与这里的库；只能选你看得到的库">
        <Select {...common} placeholder="选择知识库" options={withCurrent(options.kbs, editing?.scope.knowledge_bases)} />
      </Form.Item>
      {blind.length > 0 && (
        <Alert type="warning" showIcon style={{ marginBottom: 12 }}
          message={`这些库对该 Key 检索不到：${blind.join('、')}`}
          description="所选智能体绑定了它们，但它们不公开、也没有放行给这个 Key；需要的话加到上面的“检索放行的非公开知识库”。" />
      )}
    </>
  )
}
