import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, Select, message, Popconfirm, Space, Tag } from 'antd'
import { PlusOutlined, MessageOutlined, HistoryOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { listAgents, createAgent, updateAgent, deleteAgent, publishAgent, getAgentVersions, rollbackAgent, listModels, listTools, listKBs } from '../api'

export default function Agents() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [versionOpen, setVersionOpen] = useState(false)
  const [versions, setVersions] = useState<any[]>([])
  const [versionAgent, setVersionAgent] = useState<any>(null)
  const [models, setModels] = useState<any[]>([])
  const [tools, setTools] = useState<any[]>([])
  const [kbs, setKBs] = useState<any[]>([])
  const [form] = Form.useForm()
  const navigate = useNavigate()

  const load = async () => {
    setLoading(true)
    try {
      const [a, m, t, k]: any = await Promise.all([listAgents(), listModels(), listTools(), listKBs()])
      setData(a)
      setModels(m)
      setTools(t)
      setKBs(k)
    } catch (e: any) {
      message.error(e.response?.data?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const onSubmit = async (values: any) => {
    try {
      if (editing) await updateAgent(editing.id, values)
      else await createAgent(values)
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
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '状态', dataIndex: 'status', render: (v: string) => <Tag color={v === 'published' ? 'green' : v === 'draft' ? 'orange' : 'red'}>{v}</Tag> },
    { title: '版本', dataIndex: 'version', width: 70 },
    {
      title: '操作', render: (_: any, record: any) => (
        <Space>
          <Button size="small" icon={<MessageOutlined />} onClick={() => navigate('/chat', { state: { agentId: record.id } })}>对话</Button>
          {record.status !== 'published' && <Button size="small" type="primary" onClick={async () => { await publishAgent(record.id); load() }}>发布</Button>}
          <Button size="small" icon={<HistoryOutlined />} onClick={async () => { setVersionAgent(record); setVersions(await getAgentVersions(record.id) as any); setVersionOpen(true) }}>版本</Button>
          <Button size="small" onClick={() => { setEditing(record); form.setFieldsValue(record); setOpen(true) }}>编辑</Button>
          <Popconfirm title="确定删除？" onConfirm={async () => { await deleteAgent(record.id); load() }}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>智能体管理</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); form.resetFields(); setOpen(true) }}>新增智能体</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>
      <Modal title={editing ? '编辑智能体' : '新增智能体'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} width={640} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Form.Item name="system_prompt" label="系统提示词" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="model_id" label="模型" rules={[{ required: true }]}>
            <Select options={models.map((m: any) => ({ value: m.id, label: m.name }))} />
          </Form.Item>
          <Form.Item name="tool_ids" label="工具">
            <Select mode="multiple" options={tools.map((t: any) => ({ value: t.id, label: t.name }))} allowClear />
          </Form.Item>
          <Form.Item name="kb_ids" label="知识库">
            <Select mode="multiple" options={kbs.map((k: any) => ({ value: k.id, label: k.name }))} allowClear />
          </Form.Item>
        </Form>
      </Modal>

      <Modal title={'版本历史：' + (versionAgent?.name || '')} open={versionOpen} onCancel={() => setVersionOpen(false)} footer={null} width={560}>
        {versions.length === 0 ? '暂无版本记录' : (
          <Table
            size="small"
            rowKey="id"
            dataSource={versions}
            pagination={false}
            columns={[
              { title: '版本', dataIndex: 'version', width: 80, render: (v: number) => 'v' + v },
              { title: '发布时间', dataIndex: 'created_at', render: (v: string) => new Date(v).toLocaleString() },
              { title: '操作', width: 100, render: (_: any, rec: any) => (
                <Popconfirm title={'回滚到 v' + rec.version + '？'} onConfirm={async () => { await rollbackAgent(versionAgent.id, rec.id); message.success('已回滚'); setVersionOpen(false); load() }}>
                  <Button size="small">回滚</Button>
                </Popconfirm>
              ) },
            ]}
          />
        )}
      </Modal>
    </div>
  )
}
