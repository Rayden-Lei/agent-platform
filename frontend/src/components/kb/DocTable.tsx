import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { FileText, Play, RotateCw, Settings, Upload } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { batchDocs, deleteDoc, listDocs, reprocessDoc, resumeDoc, uploadDoc, type DocumentRow, type UploadPolicy } from '../../api'
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
import DataTable, { type DataColumn } from '../table/DataTable'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import InlineConfirm from '../ui/InlineConfirm'
import ChunkDrawer from './ChunkDrawer'
import { PROCESSING_STATUSES, docProgress, humanSeconds } from './docProgress'
import { errorText } from '../../utils/errors'

// 知识库文档页签：上传、状态 / 文件名筛选、分页、失败原因、切片抽屉、重新解析、批量删除 / 重新解析。
// 处理中的文档显示进度条（已入库 / 计划总数、速度、预计剩余），有处理中的文档时每 3 秒轮询一次，没有则停（docs/07 第 3 节）。
interface Props { kbId: number; uploadPolicy?: UploadPolicy | null; onChanged?: () => void }

// 上传前预检（服务端仍会再校验，不合规 400 / 413）：挡掉明显传不上去的文件，省得几十 MB 传完才被拒
function precheck(file: File, policy?: UploadPolicy | null): string | null {
  if (!policy) return null
  const ext = file.name.includes('.') ? file.name.split('.').pop()!.toLowerCase() : ''
  if (ext === 'xls') return `${file.name}：不支持 .xls（老版 Excel），请另存为 .xlsx 后上传`
  if (!policy.extensions.includes(ext)) return `${file.name}：不支持的文件类型，支持 ${policy.extensions.join('、')}`
  if (file.size > policy.max_mb * 1024 * 1024) return `${file.name}：超过 ${policy.max_mb} MB 上限`
  if (file.size === 0) return `${file.name}：文件是空的`
  return null
}
const PROCESSING = PROCESSING_STATUSES

// 入库进度条：shadcn 没有 progress 组件，这里用语义色自己画一条（高度固定、宽度按百分比）
function ProgressBar({ percent }: { percent: number }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${percent}%` }} />
    </div>
  )
}

// 状态单元格：处理中给进度条与速度，终态给状态标签 + 总耗时；超过阈值没心跳标"疑似中断"
function StatusCell({ doc }: { doc: DocumentRow }) {
  const p = docProgress(doc)
  if (p.stalled) {
    return (
      <span className="flex flex-wrap items-center gap-1.5">
        <StatusTag domain="document" value={doc.status} />
        <Tooltip>
          <TooltipTrigger asChild>
            <span><Badge tone="warning">疑似中断 {humanSeconds(p.stalledSeconds)}无进展</Badge></span>
          </TooltipTrigger>
          <TooltipContent>后端可能被重启或向量服务卡住了；点「继续处理」从已入库的片接着做</TooltipContent>
        </Tooltip>
        {p.percent !== null && <span className="text-[12px] text-muted-foreground">停在 {doc.chunk_count.toLocaleString()} / {(doc.chunk_total ?? 0).toLocaleString()} 片</span>}
      </span>
    )
  }
  if (doc.status === 'chunking' && p.percent !== null) {
    return (
      <div className="flex min-w-[220px] flex-col gap-1">
        <ProgressBar percent={p.percent} />
        <span className="text-[12px] text-muted-foreground">
          {doc.chunk_count.toLocaleString()} / {(doc.chunk_total ?? 0).toLocaleString()} 片
          {p.rate !== null && ` · ${p.rate.toFixed(1)} 片/秒`}
          {p.etaSeconds !== null && ` · 剩余约 ${humanSeconds(p.etaSeconds)}`}
        </span>
      </div>
    )
  }
  if (PROCESSING.has(doc.status)) {
    return (
      <span className="flex flex-wrap items-center gap-1.5">
        <StatusTag domain="document" value={doc.status} />
        <span className="text-[12px] text-muted-foreground">{doc.status === 'parsing' ? '读取并切片中' : '已上传，排队等待处理（同一时间只处理一篇）'}</span>
      </span>
    )
  }
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <StatusTag domain="document" value={doc.status} />
      {p.elapsedSeconds !== null && <span className="text-[12px] text-muted-foreground">耗时 {humanSeconds(p.elapsedSeconds)}</span>}
      {doc.status === 'failed' && doc.chunk_total ? <span className="text-[12px] text-muted-foreground">已入库 {doc.chunk_count.toLocaleString()} / {doc.chunk_total.toLocaleString()} 片，可继续</span> : null}
    </span>
  )
}

// 能否"继续处理"：失败的、或处理中但已无心跳（中断）的
const canResume = (doc: DocumentRow) => doc.status === 'failed' || docProgress(doc).stalled

export default function DocTable({ kbId, uploadPolicy, onChanged }: Props) {
  const [status, setStatus] = useState<string | undefined>()
  const [q, setQ] = useState<string | undefined>()
  const [chunkDoc, setChunkDoc] = useState<DocumentRow | null>(null)
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const filters = useMemo(() => ({ status, q }), [status, q])
  const list = usePagedList<DocumentRow>((params) => listDocs(kbId, params), { filters, pageSize: 10, selectable: true })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload(); onChanged?.() })
  const processing = list.items.some((d) => PROCESSING.has(d.status))

  useEffect(() => {
    if (!processing) return
    const timer = setInterval(() => { if (document.visibilityState === 'visible') { list.reload(); onChanged?.() } }, 3000)
    return () => clearInterval(timer)
  }, [processing, list.reload, onChanged])

  const act = async (fn: () => Promise<unknown>, okText: string, fallback: string) => {
    try { await fn(); toast.success(okText); list.reload(); onChanged?.() } catch (e) { toast.error(errorText(e, fallback)) }
  }

  // 一次选多个文件时按顺序传：并发上传几个大文件会互相抢带宽，进度也没法读
  const onPick = async (files: FileList | null) => {
    if (!files?.length) return
    for (const file of Array.from(files)) {
      const problem = precheck(file, uploadPolicy)
      if (problem) { toast.error(problem); continue }
      setUploading({ name: file.name, percent: 0 })
      try {
        await uploadDoc(kbId, file, (percent) => setUploading({ name: file.name, percent }))
        toast.success(`${file.name} 上传完成，已进入处理队列`)
      } catch (e) { toast.error(errorText(e, `${file.name} 上传失败`)) }
    }
    setUploading(null)
    if (fileRef.current) fileRef.current.value = ''
    list.reload(); onChanged?.()
  }

  const empty = <EmptyState description={status || q ? '没有匹配的文档' : '还没有文档，点右上角上传（PDF / Word / Markdown / TXT）'} />

  const columns: DataColumn<DocumentRow>[] = [
    { key: 'name', header: '文件名', primary: true, sortable: true, width: 220, cell: (d) => <span className="block truncate font-medium">{d.name}</span> },
    { key: 'file_type', header: '类型', width: 80, hideOnMobile: true, cell: (d) => d.file_type.toUpperCase() },
    { key: 'status', header: '状态 / 进度', sortable: true, width: 260, cell: (d) => <StatusCell doc={d} /> },
    {
      key: 'chunk_count', header: '切片', width: 110, align: 'right', sortable: true, hideOnMobile: true,
      cell: (d) => (d.chunk_total && d.chunk_total !== d.chunk_count ? `${d.chunk_count.toLocaleString()} / ${d.chunk_total.toLocaleString()}` : d.chunk_count.toLocaleString()),
    },
    {
      key: 'error', header: '失败原因', hideOnMobile: true,
      cell: (d) => (d.error ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="block truncate text-[13px] text-destructive">{d.error}</span>
          </TooltipTrigger>
          <TooltipContent>{d.error}</TooltipContent>
        </Tooltip>
      ) : '-'),
    },
    { key: 'created_at', header: '上传时间', width: 170, sortable: true, hideOnMobile: true, cell: (d) => <TimeCell value={d.created_at} /> },
    {
      key: 'actions', header: '操作', width: 330, pinRight: true,
      cell: (d) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" icon={<FileText className="size-3.5" />} disabled={d.status !== 'ready'} onClick={() => setChunkDoc(d)}>切片</Button>
          {canResume(d) && (
            <InlineConfirm message={`从已入库的第 ${d.chunk_count.toLocaleString()} 片接着处理（切片参数没变时不重来）？`} onConfirm={() => act(() => resumeDoc(kbId, d.id), '已排队继续处理', '继续处理失败')}>
              <Button size="sm" variant="primary" icon={<Play className="size-3.5" />}>继续处理</Button>
            </InlineConfirm>
          )}
          {/* 处理中不能重新解析：后端 400，这里直接置灰 */}
          {PROCESSING.has(d.status) ? (
            <Button size="sm" variant="secondary" icon={<RotateCw className="size-3.5" />} disabled>重新解析</Button>
          ) : (
            <InlineConfirm message="重新解析会清掉旧切片并按当前切片参数重建" danger onConfirm={() => act(() => reprocessDoc(kbId, d.id), '已排队重新解析', '重新解析失败')}>
              <Button size="sm" variant="secondary" icon={<RotateCw className="size-3.5" />}>重新解析</Button>
            </InlineConfirm>
          )}
          <InlineConfirm message="确定删除该文档？" danger onConfirm={() => act(() => deleteDoc(kbId, d.id), '已删除', '删除失败')}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]

  return (
    <div className="flex flex-col gap-2">
      <FilterBar
        onReset={() => { setStatus(undefined); setQ(undefined) }}
        onRefresh={list.reload}
        loading={list.loading}
        extra={
          <>
            <input
              ref={fileRef}
              type="file"
              multiple
              className="hidden"
              accept={uploadPolicy?.extensions.map((e) => '.' + e).join(',')}
              onChange={(e) => onPick(e.target.files)}
            />
            <Button variant="primary" size="sm" disabled={!!uploading} icon={<Upload className="size-3.5" />} onClick={() => fileRef.current?.click()}>
              {uploading ? `上传中 ${uploading.percent}%` : '上传文档'}
            </Button>
          </>
        }
      >
        <SearchInput value={q} onChange={setQ} placeholder="搜索文件名" width={200} />
        <Select value={status ?? 'all'} onValueChange={(v) => setStatus(v === 'all' ? undefined : v)}>
          <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="状态">
            <SelectValue placeholder="状态" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部状态</SelectItem>
            {statusOptions('document').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
        {processing && <span className="text-[12px] text-primary">有文档处理中，每 3 秒自动刷新</span>}
        <Tooltip>
          <TooltipTrigger asChild>
            <Link to="/system-settings" className="inline-flex h-7 items-center gap-1 rounded-lg px-2 text-[12.5px] font-medium text-muted-foreground hover:bg-accent hover:text-foreground">
              <Settings className="size-3.5" />导入设置
            </Link>
          </TooltipTrigger>
          <TooltipContent>调整并发向量化请求数、每批切片数等导入参数（管理员可改）</TooltipContent>
        </Tooltip>
      </FilterBar>

      <BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'reprocess', label: '批量重新解析', confirm: `重新解析选中的 ${list.selectedKeys.length} 个文档？旧切片会被清掉`, run: () => batch.run(() => batchDocs(kbId, list.selectedKeys, 'reprocess'), '已排队重新解析') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个文档？`, run: () => batch.run(() => batchDocs(kbId, list.selectedKeys, 'delete'), '已删除') },
      ]} />

      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(d) => d.id}
        loading={list.loading}
        error={list.error}
        empty={empty}
        onRetry={list.reload}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onPageChange={list.load}
        sort={list.sort}
        onSortChange={list.setSort}
        selectable
        selectedKeys={list.selectedKeys}
        onSelectionChange={list.setSelectedKeys}
      />

      <ChunkDrawer kbId={kbId} doc={chunkDoc} onClose={() => setChunkDoc(null)} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((d) => d.id === id)?.name} />
    </div>
  )
}
