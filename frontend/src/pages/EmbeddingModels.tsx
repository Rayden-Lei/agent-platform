import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Binary, Plus } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import {
  batchEmbeddingModels, deleteEmbeddingModel, listEmbeddingModels, testEmbeddingModel,
  toggleEmbeddingModel, type EmbeddingModelRow,
} from '../api'
import { useAuth } from '../store/auth'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useSystemStatus } from '../hooks/useSystemStatus'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import EmbeddingModelForm from '../components/embedding/EmbeddingModelForm'
import { buildEmbeddingColumns } from '../components/embedding/embeddingColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

type Filters = { q?: string; provider?: string; is_enabled?: string }
const DEFAULTS: Filters = { q: undefined, provider: undefined, is_enabled: undefined }

// 向量模型（docs/04 4.3b）：知识库建库时从这里选一个绑定，入库与检索都按它走。
// 与「模型」页分开：那边是对话模型（chat/completions），这边是向量模型（embeddings），协议与字段都不同。
// 2026-11-08 起才真正生效 —— 此前知识库上那个 embedding_model 字段只落库不参与向量化。
export default function EmbeddingModels() {
  const role = useAuth((s) => s.user?.role)
  const canManage = role === 'admin'
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<EmbeddingModelRow | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)
  // 切片表列宽从系统状态取：它是维度校验的唯一依据，页面不自己硬编码 1024
  const { status } = useSystemStatus()
  const requiredDim = status?.embedding?.dim ?? 1024

  const list = usePagedList<EmbeddingModelRow>(listEmbeddingModels, {
    filters, selectable: canManage,
    emptyText: (
      <EmptyState
        description="还没有向量模型。建知识库前要先在这里配一个：文档入库与检索都按它把文本转成向量。"
        action={canManage ? { label: '新增向量模型', onClick: () => { setEditing(null); setFormOpen(true) } } : undefined}
      />
    ),
  })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })

  // 连通测试：结果直接提示。失败不抛错（后端返回 ok=false），要能显示具体原因
  const onTest = async (m: EmbeddingModelRow) => {
    setTestingId(m.id)
    try {
      const res = await testEmbeddingModel(m.id)
      if (res.ok) toast.success(res.reply || '连通正常')
      else toast.error(`连通失败：${res.error || '未知错误'}`)
    } catch (e) { toast.error(errorText(e, '测试失败')) } finally { setTestingId(null) }
  }
  const onToggle = async (m: EmbeddingModelRow) => {
    try { await toggleEmbeddingModel(m.id); list.reload() } catch (e) { toast.error(errorText(e, '操作失败')) }
  }
  const onDelete = async (m: EmbeddingModelRow) => {
    try { await deleteEmbeddingModel(m.id); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  const columns = useMemo(
    () => buildEmbeddingColumns({
      onOpen: (m) => { setEditing(m); setFormOpen(true) },
      onToggle, onTest, onEdit: (m) => { setEditing(m); setFormOpen(true) }, onDelete, testingId, canManage, requiredDim,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [testingId, canManage, requiredDim],
  )

  return (
    <ListPage
      header={
        <PageHeader
          icon={<Binary />}
          title="向量模型"
          description={`知识库入库与检索用的 embedding 模型；维度必须等于切片表列宽（${requiredDim}）。`}
          extra={canManage && <Button variant="primary" size="md" icon={<Plus />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增向量模型</Button>}
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}
          activeCount={Object.values(filters).filter(Boolean).length}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称" />
          <Select value={filters.provider ?? 'all'} onValueChange={(v) => setFilters({ provider: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[130px] text-[13px]" aria-label="服务商"><SelectValue placeholder="服务商" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部服务商</SelectItem>
              <SelectItem value="openai">OpenAI 兼容</SelectItem>
              <SelectItem value="qwen">通义千问</SelectItem>
              <SelectItem value="deepseek">DeepSeek</SelectItem>
              <SelectItem value="zhipu">智谱</SelectItem>
              <SelectItem value="moonshot">月之暗面</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.is_enabled ?? 'all'} onValueChange={(v) => setFilters({ is_enabled: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[100px] text-[13px]" aria-label="状态"><SelectValue placeholder="状态" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="true">启用</SelectItem>
              <SelectItem value="false">停用</SelectItem>
            </SelectContent>
          </Select>
        </FilterBar>
      }
      batch={
        <BatchActionBar
          count={list.selectedKeys.length}
          onClear={list.clearSelection}
          running={batch.running}
          actions={[{
            key: 'delete', label: '批量删除', danger: true,
            confirm: `删除选中的 ${list.selectedKeys.length} 个向量模型？被知识库绑定的会失败`,
            run: () => batch.run(() => batchEmbeddingModels(list.selectedKeys, 'delete'), '已删除'),
          }]}
        />
      }
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        empty={list.emptyText}
        onRetry={list.reload}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onPageChange={list.load}
        sort={list.sort}
        onSortChange={list.setSort}
        selectable={canManage}
        selectedKeys={list.selectedKeys}
        onSelectionChange={list.setSelectedKeys}
      />
      <EmbeddingModelForm
        open={formOpen}
        editing={editing}
        requiredDim={requiredDim}
        onClose={() => setFormOpen(false)}
        onSaved={list.reload}
      />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((m) => m.id === id)?.name} />
    </ListPage>
  )
}
