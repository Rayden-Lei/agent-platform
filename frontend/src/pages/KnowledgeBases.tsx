import { useEffect, useState } from 'react'
import { Alert, Table, Button, Modal, Form, Input, InputNumber, message, Popconfirm, Space, Drawer, Upload, Tag, List, Divider, Descriptions, Empty, Typography, Card, Switch, Select } from 'antd'
import { PlusOutlined, UploadOutlined, FolderOpenOutlined, FileTextOutlined, SearchOutlined } from '@ant-design/icons'
import { listKBs, createKB, updateKB, deleteKB, listDocs, uploadDoc, searchKB, listDocChunks, getSystemStatus, OPTIONS_PAGE, type EmbeddingStatus } from '../api'
import { usePagedList } from '../hooks/usePagedList'

const { Paragraph, Text } = Typography

// 知识库页：库的增删改（含公开/角色可见权限）+ 抽屉内的文档上传与列表、
// 检索评测（带 debug 统计）与切片查看。向量后端降级时页头给出醒目警告，
// 避免使用者误判检索质量。
export default function KnowledgeBases() {
  const { tableProps, reload } = usePagedList(listKBs)
  const [open, setOpen] = useState(false)
  // drawerKb 为当前打开文档抽屉的知识库；editingId 非空表示编辑权限弹窗（否则为新建）
  const [drawerKb, setDrawerKb] = useState<any>(null)
  const [docs, setDocs] = useState<any[]>([])
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [results, setResults] = useState<any[]>([])
  const [stats, setStats] = useState<any>(null)
  const [searching, setSearching] = useState(false)
  const [chunkDoc, setChunkDoc] = useState<any>(null)
  const [chunks, setChunks] = useState<any[]>([])
  const [chunkPage, setChunkPage] = useState({ page: 1, pageSize: 20, total: 0 })
  const [chunksLoading, setChunksLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [embedStatus, setEmbedStatus] = useState<EmbeddingStatus | null>(null)
  const [statusError, setStatusError] = useState('')
  const [form] = Form.useForm()

  // 向量后端降级时检索质量会明显下降，必须在建库/上传的页面直接告诉使用者，而不是让他们猜
  useEffect(() => {
    let alive = true
    getSystemStatus()
      .then((s) => { if (alive) { setEmbedStatus(s.embedding); setStatusError('') } })
      .catch((e: any) => { if (alive) { setEmbedStatus(null); setStatusError(e.response?.data?.detail || '无法获取向量后端状态') } })
    return () => { alive = false }
  }, [])

  // 加载指定知识库的文档列表（分页取前 100 条）
  const loadDocs = async (kbId: number) => {
    try { setDocs((await listDocs(kbId, OPTIONS_PAGE)).items) } catch (e: any) { message.error(e.response?.data?.detail || '加载文档失败') }
  }

  // 打开文档抽屉：重置检索/切片状态后拉取文档列表
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

  // 新增/编辑共用提交：editingId 非空为编辑（改名称/切片参数/权限），否则为新建
  const onSubmit = async (values: any) => {
    try {
      if (editingId) {
        await updateKB(editingId, values)
        message.success('权限已保存')
      } else {
        await createKB(values)
        message.success('创建成功')
      }
      setOpen(false)
      setEditingId(null)
      form.resetFields()
      reload()
    } catch (e: any) { message.error(e.response?.data?.detail || '保存失败') }
  }

  // 按文档分页加载切片；切片抽屉自管分页（chunkPage），不走 usePagedList
  const loadChunks = async (doc: any, page = 1, pageSize = 20) => {
    setChunkDoc(doc)
    setChunks([])
    setChunksLoading(true)
    try {
      const res = await listDocChunks(drawerKb.id, doc.id, { page, page_size: pageSize })
      setChunks(res.items)
      setChunkPage({ page: res.page, pageSize: res.page_size, total: res.total })
      setChunkDoc({ ...doc, chunk_count: res.total })
    } catch (e: any) { message.error(e.response?.data?.detail || '加载切片失败') } finally { setChunksLoading(false) }
  }

  // 检索评测：带 debug 标记请求，返回候选数/词法命中/分数等统计，便于评估检索质量
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
    // 权限列：公开直接显示，受限时展示可见角色列表
    { title: '权限', dataIndex: 'is_public', width: 140, render: (v: boolean, r: any) => v ? <Tag color="green">公开</Tag> : <Tag color="orange">受限 {((r.visible_roles || []).join('/')) || ''}</Tag> },
    { title: '切片大小', dataIndex: 'chunk_size', width: 100 },
    { title: '操作', render: (_: any, r: any) => (
      <Space>
        <Button size="small" icon={<FolderOpenOutlined />} onClick={() => openDocs(r)}>文档</Button>
        <Button size="small" onClick={() => { form.setFieldsValue({ ...r, name: r.name, description: r.description, embedding_model: r.embedding_model || 'text-embedding-3-small', chunk_size: r.chunk_size, chunk_overlap: r.chunk_overlap, is_public: r.is_public, visible_roles: r.visible_roles || [] }); setEditingId(r.id); setOpen(true) }}>权限</Button>
        <Popconfirm title="确定删除？" onConfirm={async () => { try { await deleteKB(r.id); reload() } catch (e: any) { message.error(e.response?.data?.detail || '删除失败') } }}><Button size="small" danger>删除</Button></Popconfirm>
      </Space>
    ) },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexShrink: 0 }}>
        <h2>知识库</h2>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { form.resetFields(); setEditingId(null); setOpen(true) }}>新建知识库</Button>
      </div>
      {statusError && <Alert type="warning" showIcon style={{ flexShrink: 0 }} message={statusError} />}
      {embedStatus?.mode === 'hash' && (
        <Alert
          type="warning"
          showIcon
          style={{ flexShrink: 0 }}
          message="检索当前使用本地 hash 兜底向量，语义召回能力有限"
          description={(
            <div style={{ fontSize: 13 }}>
              <div>{embedStatus.reason}</div>
              {embedStatus.last_error && (
                <div style={{ marginTop: 4 }}>最近一次失败：{embedStatus.last_error.at}　{embedStatus.last_error.error}</div>
              )}
              <div style={{ marginTop: 4 }}>恢复方式：配置 EMBEDDING_API_BASE 与 EMBEDDING_API_KEY 后重启后端，并重新上传已有文档以重建向量。</div>
            </div>
          )}
        />
      )}
      <div className="fixed-table-wrapper">
        <Table rowKey="id" {...tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      </div>

      <Modal title={editingId ? '编辑知识库权限' : '新建知识库'} open={open} onCancel={() => setOpen(false)} onOk={() => form.submit()} destroyOnClose>
        <Form form={form} layout="vertical" onFinish={onSubmit} initialValues={{ chunk_size: 500, chunk_overlap: 50, embedding_model: 'text-embedding-3-small', is_public: true, visible_roles: [] }}>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="description" label="描述"><Input /></Form.Item>
          <Form.Item name="embedding_model" label="向量模型"><Input /></Form.Item>
          <Form.Item name="chunk_size" label="切片大小"><InputNumber min={50} max={5000} /></Form.Item>
          <Form.Item name="chunk_overlap" label="切片重叠"><InputNumber min={0} max={1000} /></Form.Item>
          <Divider style={{ margin: '12px 0' }}>访问权限</Divider>
          <Form.Item name="is_public" label="公开（所有角色可见）" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.is_public !== cur.is_public}>
            {({ getFieldValue }) => !getFieldValue('is_public') && (
              <Form.Item name="visible_roles" label="可见角色（非公开时生效）">
                <Select mode="multiple" placeholder="选择可访问的角色" options={[{ value: 'admin', label: '管理员' }, { value: 'developer', label: '开发者' }, { value: 'caller', label: '调用者' }]} />
              </Form.Item>
            )}
          </Form.Item>
        </Form>
      </Modal>

      <Drawer title={'知识库：' + (drawerKb?.name || '')} open={!!drawerKb} onClose={() => setDrawerKb(null)} width={720}>
        <Upload showUploadList={false} customRequest={async ({ file, onSuccess }) => {
          // 上传成功后后端异步解析入库，延时 1.5s 再刷新列表，给解析留缓冲
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
        <div style={{ marginBottom: 12, color: '#64748b' }}>共 {chunkPage.total} 个切片</div>
        <List
          loading={chunksLoading}
          dataSource={chunks}
          pagination={{ current: chunkPage.page, pageSize: chunkPage.pageSize, total: chunkPage.total, size: 'small', showSizeChanger: false, onChange: (p) => loadChunks(chunkDoc, p, chunkPage.pageSize) }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无切片" /> }}
          renderItem={(c: any, idx) => (
            <List.Item style={{ display: 'block', padding: '12px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8, marginBottom: 6 }}>
                <Text strong>#{(chunkPage.page - 1) * chunkPage.pageSize + idx + 1}</Text>
                <Space size={6} wrap>
                  <Tag color="blue">{c.token_count ?? 0} tokens</Tag>
                  {/* 入库时的向量后端：hash 表示这批切片是降级入库的，换回真实模型后需要重新处理 */}
                  {c.meta?.embedding_mode === 'hash' && <Tag color="orange">hash 向量</Tag>}
                  {c.meta?.embedding_mode === 'model' && <Tag color="green">{c.meta.embedding_model}</Tag>}
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
