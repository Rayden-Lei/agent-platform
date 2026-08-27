import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Drawer, Upload, Tag, List, Divider } from 'antd'
import { PlusOutlined, UploadOutlined, FolderOpenOutlined } from '@ant-design/icons'
import { listKBs, createKB, deleteKB, listDocs, uploadDoc, searchKB } from '../api'

export default function KnowledgeBases() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [drawerKb, setDrawerKb] = useState<any>(null)
  const [docs, setDocs] = useState<any[]>([])
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<any[]>([])
  const [form] = Form.useForm()

  const load = async () => {
    setLoading(true)
    try { setData(await listKBs() as any) } catch (e: any) { message.error(e.response?.data?.detail || '加载失败') } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const loadDocs = async (kbId: number) => {
    try { setDocs(await listDocs(kbId) as any) } catch (e: any) { message.error('加载文档失败') }
  }

  const openDocs = (kb: any) => {
    setDrawerKb(kb)
    setDocs([])
    setResults([])
    setQuery('')
    loadDocs(kb.id)
  }

  const onSubmit = async (values: any) => {
    try {
      await createKB(values)
      message.success('创建成功')
      setOpen(false)
      form.resetFields()
      load()
    } catch (e: any) { message.error(e.response?.data?.detail || '创建失败') }
  }

  const doSearch = async () => {
    if (!query.trim()) return
    try {
      const res: any = await searchKB(drawerKb.id, { query, top_k: 4 })
      setResults(res.items || [])
    } catch (e: any) { message.error('检索失败') }
  }

  const columns = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '名称', dataIndex: 'name' },
    { title: '描述', dataIndex: 'description', ellipsis: true },
    { title: '切片大小', dataIndex: 'chunk_size', width: 100 },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openDocs(r)}>文档</Button>
        <Popconfirm title="确定删除？" onConfirm={async () => { await deleteKB(r.id); load() }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>知识库</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setOpen(true) }}>新建知识库</Button>
      </div>
      <div className="fixed-table-wrapper">
        <Table rowKey="id" loading={loading} dataSource={data} columns={columns} scroll={{ x: 'max-content' }} pagination={{ position: ['bottomRight'], showSizeChanger: true, showTotal: (t) => '共 ' + t + ' 条' }} />
      </div>

      <Modal title="新建知识库" open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ chunk_size: 500, chunk_overlap: 50, embedding_model: 'text-embedding-3-small' }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Form.Item name="embedding_model" label="向量模型"><Input /></Form.Item>
          <Form.Item name="chunk_size" label="切片大小"><InputNumber min={50} max={5000} /></Form.Item>
          <Form.Item name="chunk_overlap" label="切片重叠"><InputNumber min={0} max={1000} /></Form.Item>
        </Form>
      </Modal>

      <Drawer title={'知识库：' + (drawerKb?.name || '')} open={!!drawerKb} onClose={() => setDrawerKb(null)} width={640}>
        <Upload showUploadList={false} customRequest={async ({ file, onSuccess }) => {
          try { await uploadDoc(drawerKb.id, file as File); message.success('上传成功，后台处理中'); setTimeout(() => loadDocs(drawerKb.id), 1500) } catch (e: any) { message.error('上传失败') }
          onSuccess?.({})
        }}>
          <Button icon={<UploadOutlined />}>上传文档(PDF/Word/MD/TXT)</Button>
        </Upload>
        <Divider>文档列表</Divider>
        <List
          size="small"
          dataSource={docs}
          renderItem={(d: any) => (
            <List.Item>
              <Space>
                <span>{d.name}</span>
                <Tag color={d.status === 'ready' ? 'green' : d.status === 'failed' ? 'red' : 'blue'}>{d.status}</Tag>
                {d.chunk_count > 0 && <span style={{ color: '#999' }}>{d.chunk_count} 片段</span>}
              </Space>
            </List.Item>
          )}
        />
        <Divider>检索测试</Divider>
        <Space.Compact style={{ width: '100%' }}>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入检索内容" onPressEnter={doSearch} />
          <Button type="primary" onClick={doSearch}>检索</Button>
        </Space.Compact>
        <List
          style={{ marginTop: 12 }}
          dataSource={results}
          renderItem={(r: any) => (
            <List.Item>
              <div>
                <div style={{ marginBottom: 4 }}><Tag color="blue">score: {r.score}</Tag>{r.doc_name}</div>
                <div style={{ color: '#666' }}>{r.content}</div>
              </div>
            </List.Item>
          )}
        />
      </Drawer>
    </div>
  )
}
