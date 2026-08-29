import { useEffect, useState } from 'react'
import { Table, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Drawer, Upload, Tag, List, Divider, Descriptions, Empty, Typography, Card } from 'antd'
import { PlusOutlined, UploadOutlined, FolderOpenOutlined, FileTextOutlined, SearchOutlined } from '@ant-design/icons'
import { listKBs, createKB, deleteKB, listDocs, uploadDoc, searchKB, listDocChunks } from '../api'

const { Paragraph, Text } = Typography

export default function KnowledgeBases() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [drawerKb, setDrawerKb] = useState<any>(null)
  const [docs, setDocs] = useState<any[]>([])
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [results, setResults] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [searching, setSearching] = useState(false)
  const [chunkDoc, setChunkDoc] = useState<any>(null)
  const [chunks, setChunks] = useState<any[]>([])
  const [chunksLoading, setChunksLoading] = useState(false)
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
    setStats(null)
    setQuery('')
    setChunkDoc(null)
    setChunks([])
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

  const loadChunks = async (doc: any) => {
    setChunkDoc(doc)
    setChunks([])
    setChunksLoading(true)
    try {
      const res: any = await listDocChunks(drawerKb.id, doc.id)
      setChunks(res.items || [])
      setChunkDoc({ ...doc, chunk_count: res.chunk_count ?? doc.chunk_count })
    } catch (e: any) { message.error('加载切片失败') } finally { setChunksLoading(false) }
  }

  const doSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const res: any = await searchKB(drawerKb.id, { query, top_k: topK, debug: true })
      setResults(res.items || [])
      setStats(res.stats || null)
    } catch (e: any) { message.error('检索失败') } finally { setSearching(false) }
  }

  const statusColor = (s: string) => (s === 'ready' ? 'green' : s === 'failed' ? 'red' : 'blue')

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
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
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

      <Drawer title={'知识库：' + (drawerKb?.name || '')} open={!!drawerKb} onClose={() => setDrawerKb(null)} width={720}>
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
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文档" /> }}
          renderItem={(d: any) => (
            <List.Item
              actions={[
                <Button key="c" size="small" type="link" icon={<FileTextOutlined />} disabled={d.status !== 'ready'} onClick={() => loadChunks(d)}>切片</Button>,
              ]}
            >
              <Space>
                <span>{d.name}</span>
                <Tag color={statusColor(d.status)}>{d.status}</Tag>
                {d.chunk_count > 0 && <span style={{ color: '#94a3b8' }}>{d.chunk_count} 片段</span>}
              </Space>
            </List.Item>
          )}
        />
        <Divider>检索评测</Divider>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入检索内容" onPressEnter={doSearch} style={{ flex: 1 }} />
          <InputNumber min={1} max={50} value={topK} onChange={(v) => setTopK(v ?? 5)} addonBefore="Top K" style={{ width: 120 }} />
          <Button type="primary" icon={<SearchOutlined />} loading={searching} onClick={doSearch}>检索</Button>
        </div>

        {stats && (
          <div className="search-stats" style={{ marginTop: 12 }}>
            <Descriptions size="small" bordered column={3} items={[
              { key: 'query', label: 'Query', children: <Text copyable={{ text: stats.query }}>{stats.query}</Text>, span: 3 },
              { key: 'keywords', label: '关键词', span: 3, children: (stats.keywords || []).length ? (stats.keywords || []).map((k: string) => <Tag key={k} color="cyan">{k}</Tag>) : '—' },
              { key: 'candidate_count', label: '候选数', children: stats.candidate_count },
              { key: 'returned', label: '返回数', children: stats.returned },
              { key: 'top_score', label: '最高分', children: <Text strong style={{ color: '#1e40af' }}>{stats.top_score}</Text> },
              { key: 'mean_score', label: '平均分', children: stats.mean_score },
              { key: 'lexical_hit_count', label: '词法命中', children: stats.lexical_hit_count },
              { key: 'empty', label: '', children: '' },
            ]} />
          </div>
        )}

        {results.length === 0 ? (
          <Empty style={{ marginTop: 16 }} image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无检索结果" />
        ) : (
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
            {results.map((r: any, idx) => (
              <Card key={idx} size="small" className="search-result-card" title={
                <Space size={8} wrap>
                  <Tag color="blue">#{idx + 1}</Tag>
                  <Text strong>{r.doc_name || '文档 ' + r.doc_id}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>score {typeof r.score === 'number' ? r.score.toFixed(4) : r.score}</Text>
                </Space>
              }>
                <Paragraph style={{ marginBottom: 8, fontSize: 13 }} ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>{r.content}</Paragraph>
                {typeof r.vector_score === 'number' && (
                  <Space size={6} wrap>
                    <Tag>向量 {r.vector_score}</Tag>
                    <Tag>词法 {r.keyword_score}</Tag>
                    {(r.matched_keywords || []).map((k: string) => <Tag key={k} color="cyan">{k}</Tag>)}
                  </Space>
                )}
              </Card>
            ))}
          </div>
        )}
      </Drawer>

      <Drawer title={'切片：' + (chunkDoc?.name || '')} open={!!chunkDoc} onClose={() => setChunkDoc(null)} width={760}>
        <div style={{ marginBottom: 12, color: '#64748b' }}>共 {chunks.length} 个切片</div>
        <List
          loading={chunksLoading}
          dataSource={chunks}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无切片" /> }}
          renderItem={(c: any, idx) => (
            <List.Item style={{ display: 'block', padding: '12px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
                <Text strong>#{idx + 1}</Text>
                <Space size={6} wrap>
                  <Tag color="blue">{c.token_count ?? 0} tokens</Tag>
                </Space>
              </div>
              {c.meta && Object.keys(c.meta).length > 0 && (
                <div style={{ marginBottom: 6, fontSize: 12, color: '#94a3b8', wordBreak: 'break-all' }}>meta: {JSON.stringify(c.meta)}</div>
              )}
              <Paragraph style={{ marginBottom: 0, fontSize: 13, color: '#334155', whiteSpace: 'pre-wrap' }} ellipsis={{ rows: 4, expandable: true, symbol: '展开' }}>{c.content}</Paragraph>
            </List.Item>
          )}
        />
      </Drawer>
    </div>
  )
}
