import { useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, InputNumber } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listModels, createModel, updateModel, deleteModel } from '../api'
import { usePagedList } from '../hooks/usePagedList'

// 模型管理页：维护 LLM 接入配置（OpenAI 兼容 / DeepSeek / 通义等）的增删改。
// api_base + api_key 构成一个可调用的模型端点，价格字段用于成本统计。
export default function Models() {
  const { tableProps, reload } = usePagedList(listModels)
  const [open, setOpen] = useState(false)
  // editing 非空表示当前弹窗处于编辑模式（提交时走 update），否则为新增（走 create）
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

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

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '提供商', dataIndex: 'provider' },
    { title: '模型名', dataIndex: 'model_name' },
    { title: 'API 地址', dataIndex: 'api_base', ellipsis: true },
    { title: '状态', dataIndex: 'is_enabled', render: (v: boolean) => <Tag color={v ? 'green' : 'red'}>{v ? '启用' : '停用'}</Tag> },
    {
      title: '操作', render: (_: any, record: any) => (
        <Space>
          {/* 编辑时把 api_key 强制清空：密钥不明文回显，需要重新填写（表单 required 兜底），避免泄露 */}
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
      <Modal title={editing ? '编辑模型' : '新增模型'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
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
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}><Input.Password placeholder="编辑时需重新填写" /></Form.Item>
          <Form.Item name="model_name" label="模型名" rules={[{ required: true, message: '请输入模型名' }]}><Input placeholder="deepseek-v4-pro-0813" /></Form.Item>
          <Form.Item name="price_input" label="输入价格(元/百万token)"><InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="可选" /></Form.Item>
          <Form.Item name="price_output" label="输出价格(元/百万token)"><InputNumber min={0} step={0.1} style={{ width: '100%' }} placeholder="可选" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
