import { useCallback, useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, InputNumber, Tooltip } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listModels, createModel, updateModel, deleteModel, testModel, getSystemStatus } from '../api'
import type { ModelBreakerStatus } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// 模型管理页：维护 LLM 接入配置（OpenAI 兼容 / DeepSeek / 通义等）的增删改、连通测试。
// api_base + api_key 构成一个可调用的模型端点，价格字段用于成本统计。
// 熔断状态来自 /system/status.model_breakers：连续失败达阈值的模型在开启期内直接 503，连通测试成功即恢复。
export default function Models() {
  const { tableProps, reload } = usePagedList(listModels)
  const [open, setOpen] = useState(false)
  // editing 非空表示当前弹窗处于编辑模式（提交时走 update），否则为新增（走 create）
  const [editing, setEditing] = useState<any>(null)
  // model_id → 熔断器状态；只含非 closed 的模型
  const [breakers, setBreakers] = useState<Record<number, ModelBreakerStatus>>({})
  const [testingId, setTestingId] = useState<number | null>(null)
  const [form] = Form.useForm()

  // 熔断状态读取失败只影响标签展示，不阻塞页面；静默更新，不清空已有数据
  const loadBreakers = useCallback(async () => {
    try {
      const status = await getSystemStatus()
      setBreakers(Object.fromEntries(status.model_breakers.map((b) => [b.model_id, b])))
    } catch { /* 状态接口不可用时保留上一次的标签 */ }
  }, [])
  useEffect(() => { loadBreakers() }, [loadBreakers])

  // 新增/编辑共用提交：editing 非空走更新接口，否则走创建接口；成功后关弹窗并刷新列表
  const onSubmit = async (values: any) => {
    try {
      if (editing) await updateModel(editing.id, values)
      else await createModel(values)
      message.success('保存成功')
      setOpen(false)
      reload()
    } catch (e: any) {
      message.error(e.response?.data?.detail || '保存失败')
    }
  }

  // 连通测试：结果直接提示；成功会关闭该模型的熔断，所以测完刷新一次熔断标签
  const onTest = async (record: any) => {
    setTestingId(record.id)
    try {
      const res = await testModel(record.id)
      if (res.data.ok) message.success(`连通正常：${res.data.reply || ''}`)
      else message.error(`连通失败：${res.data.error || '未知错误'}`)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '测试失败')
    } finally {
      setTestingId(null)
      loadBreakers()
    }
  }

  const renderStatus = (enabled: boolean, record: any) => {
    const breaker = breakers[record.id]
    return (
      <Space size={4}>
        <Tag color={enabled ? 'green' : 'red'}>{enabled ? '启用' : '停用'}</Tag>
        {breaker && (
          <Tooltip title={`连续失败 ${breaker.consecutive_failures} 次；点击"测试"成功后立即恢复`}>
            <Tag color="orange">{breaker.state === 'open' ? `熔断中，${breaker.retry_after_seconds} 秒后重试` : '熔断探测中'}</Tag>
          </Tooltip>
        )}
      </Space>
    )
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '提供商', dataIndex: 'provider' },
    { title: '模型名', dataIndex: 'model_name' },
    { title: 'API 地址', dataIndex: 'api_base', ellipsis: true },
    { title: '状态', dataIndex: 'is_enabled', render: renderStatus },
    {
      title: '操作', render: (_: any, record: any) => (
        <Space>
          <Button size="small" loading={testingId === record.id} onClick={() => onTest(record)}>测试</Button>
          {/* 编辑时把 api_key 强制清空（密钥不明文回显），留空提交则后端沿用原有 Key，不会误覆盖 */}
          <Button size="small" onClick={() => { setEditing(record); form.setFieldsValue({ ...record, api_key: '' }); setOpen(true) }}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={async () => { try { await deleteModel(record.id); reload() } catch (e: any) { message.error(e.response?.data?.detail || '删除失败') } }}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>模型管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增模型</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>
      <Modal title={editing ? '编辑模型' : '新增模型'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnHidden>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ provider: 'openai', api_key: '' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input /></Form.Item>
          <Form.Item name="provider" label="提供商" rules={[{ required: true }]}>
            <Select options={[
              { value: 'openai', label: 'OpenAI 兼容' },
              { value: 'deepseek', label: 'DeepSeek' },
              { value: 'qwen', label: '通义千问' },
              { value: 'moonshot', label: '月之暗面' },
              { value: 'zhipu', label: '智谱' },
            ]} />
          </Form.Item>
          <Form.Item name="api_base" label="API 地址" rules={[{ required: true, message: '请输入 API 地址' }]}><Input placeholder="https://xxx/v1" /></Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: !editing, message: '请输入 API Key' }]}><Input.Password placeholder={editing ? '留空则不修改' : '请输入 API Key'} /></Form.Item>
          <Form.Item name="model_name" label="模型名" rules={[{ required: true, message: '请输入模型名' }]}><Input placeholder="deepseek-v4-pro-0813" /></Form.Item>
          <Form.Item name="price_input" label="输入价格(元/百万token)"><InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="可选" /></Form.Item>
          <Form.Item name="price_output" label="输出价格(元/百万token)"><InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="可选" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
