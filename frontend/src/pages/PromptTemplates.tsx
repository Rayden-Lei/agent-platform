import { useMemo, useState } from 'react'
import { toast } from "sonner"
import { FileText, Plus } from 'lucide-react'
import { batchPromptTemplates, deletePromptTemplate, getPromptTemplate, listPromptTemplates, type PromptTemplateRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import TemplateForm from '../components/prompt/TemplateForm'
import TemplateDrawer from '../components/prompt/TemplateDrawer'
import { buildTemplateColumns } from '../components/prompt/templateColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

type Filters = { q?: string }
const DEFAULTS: Filters = { q: undefined }

// 提示词模板（FR-028）：列表筛选 / 排序 / 批量删除 + 编辑弹窗 + 详情抽屉（内容、版本对比回滚、绑定智能体、渲染预览；?open= 深链）。
export default function PromptTemplates() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<PromptTemplateRow | null>(null)
  const [current, setCurrent] = useState<PromptTemplateRow | null>(null)
  const list = usePagedList<PromptTemplateRow>(listPromptTemplates, { filters, selectable: true, emptyText: <EmptyState description="还没有模板。把系统提示词沉淀成带变量的模板，多个智能体共用并按版本管理。" action={{ label: '新增模板', onClick: () => { setEditing(null); setFormOpen(true) } }} /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => { const row = list.items.find((t) => t.id === id); if (row) setCurrent(row); else getPromptTemplate(id).then(setCurrent).catch((e) => toast.error(errorText(e, '模板不存在'))) })

  // 列表不下发 content，编辑前先取详情
  const onEdit = async (r: PromptTemplateRow) => {
    try { setEditing(r.content !== undefined ? r : await getPromptTemplate(r.id)); setFormOpen(true) } catch (e) { toast.error(errorText(e, '加载模板失败')) }
  }
  const onDelete = async (r: PromptTemplateRow) => { try { await deletePromptTemplate(r.id); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) } }
  const afterSave = () => { list.reload(); if (current) getPromptTemplate(current.id).then(setCurrent).catch(() => setCurrent(null)) }
  const columns = useMemo(() => buildTemplateColumns({ onOpen: setCurrent, onEdit, onDelete }), []) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<FileText />} title="提示词模板" description="带变量的系统提示词；内容或变量变化自动升版本。绑定的智能体保存草稿时按模板当前版本渲染，发布后对外生效。" extra={<Button variant="primary" size="md" icon={<Plus />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增模板</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索模板名称" />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[{ key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个模板？仍被智能体绑定的会失败并列在结果里`, run: () => batch.run(() => batchPromptTemplates(list.selectedKeys), '已删除') }]} />}
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        empty={<EmptyState description="还没有模板。把系统提示词沉淀成带变量的模板，多个智能体共用并按版本管理。" action={{ label: '新增模板', onClick: () => { setEditing(null); setFormOpen(true) } }} />}
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
      <TemplateForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={afterSave} />
      <TemplateDrawer template={current} onClose={() => setCurrent(null)} onEdit={onEdit} onChanged={afterSave} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((t) => t.id === id)?.name} />
    </ListPage>
  )
}
