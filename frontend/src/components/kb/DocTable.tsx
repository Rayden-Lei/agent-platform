import { useEffect, useMemo, useState } from 'react'
import { Button, Popconfirm, Progress, Select, Space, Table, Tag, Tooltip, Typography, Upload, message } from 'antd'
import { FileTextOutlined, PlayCircleOutlined, RedoOutlined, UploadOutlined } from '@ant-design/icons'
import { batchDocs, deleteDoc, listDocs, reprocessDoc, resumeDoc, uploadDoc, type DocumentRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import { useBatchAction } from '../../hooks/useBatchAction'
import { statusOptions } from '../../constants/status'
import FilterBar from '../layout/FilterBar'
import BatchActionBar from '../common/BatchActionBar'
import BatchResultModal from '../common/BatchResultModal'
import EmptyState from '../common/EmptyState'
import SearchInput from '../common/SearchInput'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import ChunkDrawer from './ChunkDrawer'
import { PROCESSING_STATUSES, docProgress, humanSeconds } from './docProgress'
import { errorText } from '../../utils/errors'

// 知识库文档页签：上传、状态 / 文件名筛选、分页、失败原因、切片抽屉、重新解析、批量删除 / 重新解析。
// 处理中的文档显示进度条（已入库 / 计划总数、速度、预计剩余），有处理中的文档时每 3 秒轮询一次，没有则停（docs/07 第 3 节）。
interface Props { kbId: number; onChanged?: () => void }
const PROCESSING = PROCESSING_STATUSES

// 状态单元格：处理中给进度条与速度，终态给状态标签 + 总耗时；超过阈值没心跳标"疑似中断"
function StatusCell({ doc }: { doc: DocumentRow }) {
  const p = docProgress(doc)
  if (p.stalled) {
    return (
      <Space size={6} wrap>
        <StatusTag domain="document" value={doc.status} />
        <Tooltip title="后端可能被重启或向量服务卡住了；点「继续处理」从已入库的片接着做"><Tag color="warning">疑似中断 {humanSeconds(p.stalledSeconds)}无进展</Tag></Tooltip>
        {p.percent !== null && <Typography.Text type="secondary" style={{ fontSize: 12 }}>停在 {doc.chunk_count.toLocaleString()} / {(doc.chunk_total ?? 0).toLocaleString()} 片</Typography.Text>}
      </Space>
    )
  }
  if (doc.status === 'chunking' && p.percent !== null) {
    return (
      <div style={{ minWidth: 220 }}>
        <Progress percent={p.percent} size="small" status="active" format={(v) => `${v}%`} />
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {doc.chunk_count.toLocaleString()} / {(doc.chunk_total ?? 0).toLocaleString()} 片
          {p.rate !== null && ` · ${p.rate.toFixed(1)} 片/秒`}
          {p.etaSeconds !== null && ` · 剩余约 ${humanSeconds(p.etaSeconds)}`}
        </Typography.Text>
      </div>
    )
  }
  if (PROCESSING.has(doc.status)) {
    return <Space size={6}><StatusTag domain="document" value={doc.status} /><Typography.Text type="secondary" style={{ fontSize: 12 }}>{doc.status === 'parsing' ? '读取并切片中' : '已上传，排队等待处理（同一时间只处理一篇）'}</Typography.Text></Space>
  }
  return (
    <Space size={6}>
      <StatusTag domain="document" value={doc.status} />
      {p.elapsedSeconds !== null && <Typography.Text type="secondary" style={{ fontSize: 12 }}>耗时 {humanSeconds(p.elapsedSeconds)}</Typography.Text>}
      {doc.status === 'failed' && doc.chunk_total ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>已入库 {doc.chunk_count.toLocaleString()} / {doc.chunk_total.toLocaleString()} 片，可继续</Typography.Text> : null}
    </Space>
  )
}

// 能否"继续处理"：失败的、或处理中但已无心跳（中断）的
const canResume = (doc: DocumentRow) => doc.status === 'failed' || docProgress(doc).stalled

export default function DocTable({ kbId, onChanged }: Props) {
  const [status, setStatus] = useState<string | undefined>()
  const [q, setQ] = useState<string | undefined>()
  const [chunkDoc, setChunkDoc] = useState<DocumentRow | null>(null)
  const filters = useMemo(() => ({ status, q }), [status, q])
  const list = usePagedList<DocumentRow>((params) => listDocs(kbId, params), { filters, pageSize: 10, selectable: true, emptyText: <EmptyState description={status || q ? '没有匹配的文档' : '还没有文档，点右上角上传（PDF / Word / Markdown / TXT）'} /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload(); onChanged?.() })
  const processing = list.items.some((d) => PROCESSING.has(d.status))

  useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => { if (document.visibilityState === 'visible') { list.reload(); onChanged?.() } }, 3000)
    return () => clearInterval(timer)
  }, [processing, list.reload, onChanged])

  const act = async (fn: () => Promise<unknown>, okText: string, fallback: string) => {
    try { await fn(); message.success(okText); list.reload(); onChanged?.() } catch (e) { message.error(errorText(e, fallback)) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <FilterBar onReset={() => { setStatus(undefined); setQ(undefined) }} onRefresh={list.reload} loading={list.loading}
        extra={
          <Upload showUploadList={false} multiple customRequest={async ({ file, onSuccess, onError, onProgress }) => {
            // 大文件上传要一两分钟：把浏览器到服务端的进度报给 antd（按钮上的加载态），完成后进后台队列
            try { await uploadDoc(kbId, file as File, (percent) => onProgress?.({ percent })); message.success(`${(file as File).name} 上传完成，已进入处理队列`); list.reload(); onChanged?.(); onSuccess?.({}) } catch (e) { message.error(errorText(e, `${(file as File).name} 上传失败`)); onError?.(e as Error) }
          }}>
            <Button type="primary" size="small" icon={<UploadOutlined />}>上传文档</Button>
          </Upload>
        }>
        <SearchInput value={q} onChange={setQ} placeholder="搜索文件名" width={200} />
        <Select allowClear placeholder="状态" style={{ width: 110 }} value={status} onChange={setStatus} options={statusOptions('document')} />
        {processing && <span style={{ fontSize: 12, color: '#2563eb' }}>有文档处理中，每 3 秒自动刷新</span>}
      </FilterBar>
      <BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'reprocess', label: '批量重新解析', confirm: `重新解析选中的 ${list.selectedKeys.length} 个文档？旧切片会被清掉`, run: () => batch.run(() => batchDocs(kbId, list.selectedKeys, 'reprocess'), '已排队重新解析') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个文档？`, run: () => batch.run(() => batchDocs(kbId, list.selectedKeys, 'delete'), '已删除') },
      ]} />
      <Table
        size="small"
        rowKey="id"
        {...list.tableProps}
        scroll={{ x: 'max-content' }}
        columns={[
          { title: '文件名', dataIndex: 'name', key: 'name', ...list.sortProps('name'), ellipsis: true },
          { title: '类型', dataIndex: 'file_type', width: 80, render: (v: string) => v.toUpperCase() },
          { title: '状态 / 进度', dataIndex: 'status', key: 'status', width: 260, ...list.sortProps('status'), render: (_: string, d) => <StatusCell doc={d} /> },
          { title: '切片', dataIndex: 'chunk_count', key: 'chunk_count', width: 110, align: 'right', ...list.sortProps('chunk_count'), render: (v: number, d) => (d.chunk_total && d.chunk_total !== v ? `${v.toLocaleString()} / ${d.chunk_total.toLocaleString()}` : v.toLocaleString()) },
          { title: '失败原因', dataIndex: 'error', ellipsis: true, render: (v: string | null) => (v ? <Tooltip title={v}><span style={{ color: '#dc2626' }}>{v}</span></Tooltip> : '-') },
          { title: '上传时间', dataIndex: 'created_at', key: 'created_at', width: 170, ...list.sortProps('created_at'), render: (v: string | null) => <TimeCell value={v} /> },
          {
            title: '操作', key: 'actions', width: 330, fixed: 'right',
            render: (_, d) => (
              <Space size={4}>
                <Button size="small" icon={<FileTextOutlined />} disabled={d.status !== 'ready'} onClick={() => setChunkDoc(d)}>切片</Button>
                {canResume(d) && (
                  <Popconfirm title={`从已入库的第 ${d.chunk_count.toLocaleString()} 片接着处理（切片参数没变时不重来）？`} onConfirm={() => act(() => resumeDoc(kbId, d.id), '已排队继续处理', '继续处理失败')}>
                    <Button size="small" type="primary" ghost icon={<PlayCircleOutlined />}>继续处理</Button>
                  </Popconfirm>
                )}
                <Popconfirm title="重新解析会清掉旧切片并按当前切片参数重建" onConfirm={() => act(() => reprocessDoc(kbId, d.id), '已排队重新解析', '重新解析失败')} disabled={PROCESSING.has(d.status)}>
                  <Button size="small" icon={<RedoOutlined />} disabled={PROCESSING.has(d.status)}>重新解析</Button>
                </Popconfirm>
                <Popconfirm title="确定删除该文档？" onConfirm={() => act(() => deleteDoc(kbId, d.id), '已删除', '删除失败')}><Button size="small" danger>删除</Button></Popconfirm>
              </Space>
            ),
          },
        ]}
      />
      <ChunkDrawer kbId={kbId} doc={chunkDoc} onClose={() => setChunkDoc(null)} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((d) => d.id === id)?.name} />
    </div>
  )
}
