import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag, InputNumber } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { listModels, createModel, updateModel, deleteModel } from '../api'

export default function Models() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try {
      const res: any = await listModels()
      setData(res)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const onSubmit = async (values: any) => {
    try {
      if (editing) await updateModel(editing.id, values)
      else await createModel(values)
      message.success('保存成功')
      setOpen(false)
      load()
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
          <Button size="small" onClick={() => { setEditing(record); form.setFieldsValue({ ...record, api_key: '' }); setOpen(true) }}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={async () => { await deleteModel(record.id); load() }}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>模型管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增模型</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
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
