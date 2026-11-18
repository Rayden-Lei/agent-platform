import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Binary, Plus } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import {
  batchEmbeddingModels, deleteEmbeddingModel, getEmbeddingDimOptions, listEmbeddingModels, testEmbeddingModel,
  toggleEmbeddingModel, type EmbeddingDimOptions, type EmbeddingModelRow,
} from '../api'
import { useAuth } from '../store/auth'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useAsyncData } from '../hooks/useAsyncData'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import EmbeddingModelForm from '../components/embedding/EmbeddingModelForm'
import EmbeddingModelDrawer from '../components/embedding/EmbeddingModelDrawer'
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
  // 点名称先开详情抽屉（看配置与绑定它的知识库），要改再点抽屉里的"编辑"，与对话模型页一致
  const [current, setCurrent] = useState<EmbeddingModelRow | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)
  // 受支持的维度由服务端下发（GET /embedding-models/dims）：页面不硬编码维度集合，
  // 也不硬编码 pgvector 的索引上限 —— 这两个数都在后端一处定义，服务端才是校验权威。
  // 取不到时不阻塞列表（表单里的维度是现成值，仍可编辑其他字段），但页头要说明：
  // 原来静默置 null，页头只剩"支持 () 维"，列表的"无索引"标记也全部消失，看起来像一切正常。
  const dims = useAsyncData<EmbeddingDimOptions>(getEmbeddingDimOptions, [], { errorText: '加载受支持的维度失败' })
  const dimOptions = dims.data
  const indexedDims = dimOptions?.indexed_dims ?? []

  const list = usePagedList<EmbeddingModelRow>(listEmbeddingModels, {
    filters, selectable: canManage, syncUrl: true,
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
    try { await deleteEmbeddingModel(m.id); list.reload(); if (current?.id === m.id) setCurrent(null) } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  const columns = useMemo(
    () => buildEmbeddingColumns({
      onOpen: setCurrent,
      onToggle, onTest, onEdit: (m) => { setEditing(m); setFormOpen(true) }, onDelete, testingId, canManage, indexedDims,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [testingId, canManage, dimOptions],
  )

  return (
    <ListPage
      header={
        <PageHeader
          icon={<Binary />}
          title="向量模型"
          description={dims.error
            ? `知识库入库与检索用的 embedding 模型。受支持的维度没取到（${dims.error}），下面的"无索引"标记与表单里的维度下拉会不完整，点筛选条的刷新重试。`
            : `知识库入库与检索用的 embedding 模型；不同知识库可以绑定不同维度的模型（支持 ${(dimOptions?.dims ?? []).join(' / ')} 维）。`}
          extra={canManage && <Button variant="primary" size="md" icon={<Plus />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增向量模型</Button>}
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={() => { list.reload(); dims.reload(true) }} loading={list.loading}
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
      <EmbeddingModelDrawer
        model={current}
        testing={testingId === current?.id}
        canManage={canManage}
        indexedDims={indexedDims}
        onClose={() => setCurrent(null)}
        onTest={onTest}
        onEdit={(m) => { setCurrent(null); setEditing(m); setFormOpen(true) }}
      />
      <EmbeddingModelForm
        open={formOpen}
        editing={editing}
        dimOptions={dimOptions}
        onClose={() => setFormOpen(false)}
        onSaved={() => { list.reload(); setCurrent(null) }}
      />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((m) => m.id === id)?.name} />
    </ListPage>
  )
}
