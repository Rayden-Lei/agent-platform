import { useEffect, useState } from 'react'
import { Divider, Form, Input, InputNumber, Modal, Select, message } from 'antd'
import { createApiKey, updateApiKey, type ApiKeyInput, type ApiKeyRow } from '../../api'
import type { ScopeOptions } from '../../hooks/useApiKeyScopeOptions'
import ApiKeyScopeFields from './ApiKeyScopeFields'
import { errorText } from '../../utils/errors'

// API Key 生成 / 编辑弹窗：授权范围（至少一项，docs/15 3.7.1）+ 配额、来源白名单、限速。
// 白名单用多行文本承载（一行一条），提交前拆成数组；CIDR、范围与作用域的合法性由服务端兜底（422 / 400）。作用域下拉由页面取好传入。
// initialScope：新建时预填的作用域（智能体"发布渠道"里生成仅限此智能体的 Key）
// ownerOptions：只有 admin 的 API Key 页传，新建时可以代发给某个用户（docs/15 D-15，Key 归属该用户，对方在个人中心只读查看）
interface Props {
  open: boolean; editing: ApiKeyRow | null; scopeOptions: ScopeOptions; initialScope?: Pick<ApiKeyInput, 'agent_ids'> | Pick<ApiKeyInput, 'workflow_ids'>
  ownerOptions?: { value: number; label: string }[]
  onClose: () => void; onSaved: () => void; onCreated: (key: string) => void
}
interface FormValues { name: string; owner_user_id?: number; quota: number; allowed_ips_text?: string; rate_limit_per_minute: number; agent_ids?: number[]; workflow_ids?: number[]; kb_ids?: number[] }
const splitIps = (text?: string): string[] => (text ?? '').split(/\r?\n/).map((s) => s.trim()).filter(Boolean)

export default function ApiKeyForm({ open, editing, scopeOptions, initialScope, ownerOptions, onClose, onSaved, onCreated }: Props) {
  const [form] = Form.useForm<FormValues>()
  const [submitting, setSubmitting] = useState(false)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    if (!editing && initialScope) form.setFieldsValue(initialScope)
    if (editing) form.setFieldsValue({
      name: editing.name, quota: editing.quota, allowed_ips_text: editing.allowed_ips.join('\n'), rate_limit_per_minute: editing.rate_limit_per_minute,
      agent_ids: editing.agent_ids, workflow_ids: editing.workflow_ids, kb_ids: editing.kb_ids,
    })
    // initialScope 只在打开时读一次：父组件每次渲染都传一个新对象，放进依赖会把正在填的表单反复重置
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing, form])

  const onSubmit = async (values: FormValues) => {
    const payload: ApiKeyInput = {
      name: values.name, quota: values.quota ?? 1000, allowed_ips: splitIps(values.allowed_ips_text), rate_limit_per_minute: values.rate_limit_per_minute ?? 0,
      agent_ids: values.agent_ids ?? [], workflow_ids: values.workflow_ids ?? [], kb_ids: values.kb_ids ?? [],
      ...(!editing && values.owner_user_id ? { owner_user_id: values.owner_user_id } : {}),
    }
    setSubmitting(true)
    try {
      if (editing) { await updateApiKey(editing.id, payload); message.success('已保存') } else { const res = await createApiKey(payload); onCreated(res.key) }
      onSaved()
      onClose()
    } catch (e) { message.error(errorText(e, editing ? '保存失败' : '创建失败')) } finally { setSubmitting(false) }
  }

  return (
    <Modal title={editing ? `编辑 API Key：${editing.name}` : '生成 API Key'} open={open} onCancel={onClose} onOk={() => form.submit()} confirmLoading={submitting} destroyOnHidden
      width={600} styles={{ body: { maxHeight: '65vh', overflow: 'auto' } }}>
      <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ quota: 1000, rate_limit_per_minute: 0 }}>
        <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 64 }]}><Input placeholder="如：生产环境调用" /></Form.Item>
        {!editing && ownerOptions && (
          <Form.Item name="owner_user_id" label="发放给" extra="不选则归属你自己。代发的 Key 以对方的身份与角色调用，知识库按对方能看到的校验；对方在个人中心只读查看，停用找管理员">
            <Select allowClear showSearch optionFilterProp="label" placeholder="选择用户（可选）" options={ownerOptions} />
          </Form.Item>
        )}
        <Divider orientation="left" plain style={{ margin: '4px 0 12px' }}>授权范围（只能调用这里的资源）</Divider>
        <ApiKeyScopeFields form={form} options={scopeOptions} editing={editing} />
        <Divider orientation="left" plain style={{ margin: '4px 0 12px' }}>配额与来源</Divider>
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
