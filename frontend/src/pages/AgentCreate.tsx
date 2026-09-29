import { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Select, Space, message } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { createAgent, listModels, OPTIONS_PAGE } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useGuardedNavigate } from '../hooks/useGuardedNavigate'
import { useUnsaved } from '../store/unsaved'
import PageHeader from '../components/layout/PageHeader'
import ErrorState from '../components/common/ErrorState'
import { errorText } from '../utils/errors'

// 新建智能体 /agents/new（docs/15 D-10 先建后编）：只填名称、模型、描述，存成草稿后进装配页配置提示词、知识库、工具。
// 草稿不上线，先建没有风险；调试也要挂在已有的智能体下才能按智能体算成本。
export default function AgentCreate() {
  const navigate = useNavigate()
  const guardedNavigate = useGuardedNavigate()
  const setDirty = useUnsaved((s) => s.setDirty)
  const [saving, setSaving] = useState(false)
  const models = useAsyncData(() => listModels(OPTIONS_PAGE), [], { errorText: '加载模型失败' })
  useEffect(() => () => setDirty(false), [setDirty])

  const onFinish = async (values: { name: string; model_id: number; description?: string }) => {
    setSaving(true)
    try {
      const created = await createAgent({ name: values.name, model_id: values.model_id, description: values.description || '' })
      setDirty(false)
      message.success('已创建草稿，继续装配')
      navigate(`/agents/${created.id}/edit`, { replace: true })
    } catch (e) { message.error(errorText(e, '创建失败')) } finally { setSaving(false) }
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{ flexShrink: 0 }}>
        <PageHeader icon={<RobotOutlined />} crumbs={[{ label: '智能体', to: '/agents' }, { label: '新建' }]} title="新建智能体"
          description="先定名称与模型，创建后进入装配页配置提示词、知识库与工具，并可当场调试；发布后才对外可用。" />
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        <Card style={{ maxWidth: 640 }}>
          {models.error && <div style={{ marginBottom: 12 }}><ErrorState compact message={models.error} onRetry={() => models.reload()} /></div>}
          <Form layout="vertical" onFinish={onFinish} scrollToFirstError onValuesChange={(_, all) => setDirty(Object.values(all).some((v) => v !== undefined && v !== ''))}>
            <Form.Item name="name" label="名称" rules={[{ required: true }, { max: 128 }]}><Input autoFocus /></Form.Item>
            <Form.Item name="model_id" label="模型" rules={[{ required: true }]} extra="模型参数可在装配页按智能体覆盖">
              <Select loading={models.loading} showSearch optionFilterProp="label" placeholder="选择模型"
                options={(models.data?.items ?? []).map((m) => ({ value: m.id, label: m.is_enabled ? m.name : `${m.name}（已停用）`, disabled: !m.is_enabled }))} />
            </Form.Item>
            <Form.Item name="description" label="描述" rules={[{ max: 2000 }]}><Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} /></Form.Item>
            <Space>
              <Button type="primary" htmlType="submit" loading={saving}>创建并进入装配</Button>
              <Button onClick={() => guardedNavigate('/agents')}>取消</Button>
            </Space>
          </Form>
        </Card>
      </div>
    </div>
  )
}
