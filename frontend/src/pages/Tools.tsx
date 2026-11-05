import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Plus, Wrench } from 'lucide-react'
import { batchTools, deleteTool, getTool, listTools, toggleTool, type ToolRow } from '../api'
import { useAuth } from '../store/auth'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import { statusOptions } from '../constants/status'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import ToolForm from '../components/tools/ToolForm'
import ToolTestModal from '../components/tools/ToolTestModal'
import ToolDrawer from '../components/tools/ToolDrawer'
import { buildToolColumns } from '../components/tools/toolColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

type Filters = { q?: string; type?: string; is_enabled?: string }
const DEFAULTS: Filters = { q: undefined, type: undefined, is_enabled: undefined }
const ENABLED_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }]

// 工具管理：筛选 / 排序 / 启停开关 / 批量启停删除 / 在线测试 / 详情抽屉（?open= 深链）。
export default function Tools() {
  const role = useAuth((s) => s.user?.role)
  const canManage = role === 'admin' || role === 'developer'
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ToolRow | null>(null)
  const [current, setCurrent] = useState<ToolRow | null>(null)
  const [testing, setTesting] = useState<ToolRow | null>(null)
  const list = usePagedList<ToolRow>(listTools, { filters, selectable: canManage, emptyText: <EmptyState description="还没有工具。内置工具由服务提供，HTTP 工具把任意接口声明成模型可调用的能力。" action={canManage ? { label: '新增工具', onClick: () => { setEditing(null); setFormOpen(true) } } : undefined} /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => { const row = list.items.find((t) => t.id === id); if (row) setCurrent(row); else getTool(id).then(setCurrent).catch((e) => toast.error(errorText(e, '工具不存在'))) })

  const onToggle = async (t: ToolRow) => { await toggleTool(t.id); list.reload() }
  const onDelete = async (t: ToolRow) => { try { await deleteTool(t.id); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) } }
  const onEdit = (t: ToolRow) => { setEditing(t); setFormOpen(true) }
  const columns = useMemo(() => buildToolColumns({ canManage, onOpen: setCurrent, onToggle, onTest: setTesting, onEdit, onDelete }), [canManage]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<Wrench />} title="工具管理" description="内置工具与 HTTP 接口工具；参数声明决定模型如何结构化调用，停用后智能体与工作流都不再使用。" extra={canManage && <Button variant="primary" size="md" icon={<Plus />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增工具</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称 / 描述" />
          <Select value={filters.type ?? 'all'} onValueChange={(v) => setFilters({ type: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="类型"><SelectValue placeholder="类型" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类型</SelectItem>
              {statusOptions('toolType').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.is_enabled ?? 'all'} onValueChange={(v) => setFilters({ is_enabled: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[100px] text-[13px]" aria-label="状态"><SelectValue placeholder="状态" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {ENABLED_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchTools(list.selectedKeys, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${list.selectedKeys.length} 个工具？`, run: () => batch.run(() => batchTools(list.selectedKeys, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个工具？`, run: () => batch.run(() => batchTools(list.selectedKeys, 'delete'), '已删除') },
      ]} />}
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        empty={<EmptyState description="还没有工具。内置工具由服务提供，HTTP 工具把任意接口声明成模型可调用的能力。" action={canManage ? { label: '新增工具', onClick: () => { setEditing(null); setFormOpen(true) } } : undefined} />}
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
      <ToolForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ToolTestModal tool={testing} onClose={() => setTesting(null)} />
      <ToolDrawer tool={current} canManage={canManage} onClose={() => setCurrent(null)} onTest={setTesting} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((t) => t.id === id)?.name} />
    </ListPage>
  )
}
