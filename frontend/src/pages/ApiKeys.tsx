import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { KeyRound, Plus } from 'lucide-react'
import { batchApiKeys, deleteApiKey, listApiKeys, listUsers, OPTIONS_PAGE, toggleApiKey, type ApiKeyRow } from '../api'
import { useAuth } from '../store/auth'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import { useAsyncData } from '../hooks/useAsyncData'
import { useApiKeyScopeOptions } from '../hooks/useApiKeyScopeOptions'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import ApiKeyForm from '../components/admin/ApiKeyForm'
import ApiKeyDrawer from '../components/admin/ApiKeyDrawer'
import CreatedKeyModal from '../components/admin/CreatedKeyModal'
import { buildApiKeyColumns } from '../components/admin/apiKeyColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { errorText } from '../utils/errors'

type Filters = { q?: string; is_enabled?: string; user_id?: string }
const DEFAULTS: Filters = { q: undefined, is_enabled: undefined, user_id: undefined }
const ENABLED_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '禁用' }]

// API Key 管理：筛选（admin 可按归属）/ 排序 / 启停开关 / 批量启停删除 / 详情抽屉；明文 key 只在生成时显示一次。
// developer 只看到本人创建的 Key（服务端按归属过滤），admin 看全部。
export default function ApiKeys() {
  const isAdmin = useAuth((s) => s.user?.role === 'admin')
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ApiKeyRow | null>(null)
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [current, setCurrent] = useState<ApiKeyRow | null>(null)
  const owners = useAsyncData(() => (isAdmin ? listUsers(OPTIONS_PAGE) : Promise.resolve({ items: [] as { id: number; username: string }[] })), [isAdmin])
  const scopeOptions = useApiKeyScopeOptions(formOpen) // 授权范围的下拉，表单打开时才取
  const list = usePagedList<ApiKeyRow>(listApiKeys, { filters, selectable: true })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => {
    const row = list.items.find((k) => k.id === id)
    if (row) setCurrent(row)
    else toast.warning('该 Key 不在当前列表里')
  })

  const openCreate = () => { setEditing(null); setFormOpen(true) }
  const onToggle = async (k: ApiKeyRow) => { await toggleApiKey(k.id); list.reload() }
  const onDelete = async (k: ApiKeyRow) => {
    try { await deleteApiKey(k.id); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  // 抽屉里点编辑：先关抽屉再开表单，避免抽屉叠抽屉
  const onEdit = (k: ApiKeyRow) => { setCurrent(null); setEditing(k); setFormOpen(true) }
  const columns = useMemo(
    () => buildApiKeyColumns({ isAdmin, onOpen: setCurrent, onToggle, onEdit, onDelete }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [isAdmin],
  )
  const empty = (
    <EmptyState description="还没有 API Key。生成后外部系统可用它调用对话与工作流接口。" action={{ label: '生成 Key', onClick: openCreate }} />
  )

  return (
    <ListPage
      header={
        <PageHeader
          icon={<KeyRound />}
          title="API Key 管理"
          description="外部调用凭据：配额、来源白名单与限速；明文只在生成时显示一次。"
          extra={<Button variant="primary" size="md" icon={<Plus />} onClick={openCreate}>生成 Key</Button>}
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称" />
          <Select value={filters.is_enabled ?? 'all'} onValueChange={(v) => setFilters({ is_enabled: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[100px] text-[13px]" aria-label="状态">
              <SelectValue placeholder="状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {ENABLED_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          {isAdmin && (
            <Select value={filters.user_id ?? 'all'} onValueChange={(v) => setFilters({ user_id: v === 'all' ? undefined : v })}>
              <SelectTrigger size="sm" className="h-8 w-[150px] text-[13px]" aria-label="归属">
                <SelectValue placeholder="归属" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部归属</SelectItem>
                {(owners.data?.items ?? []).map((u) => <SelectItem key={u.id} value={String(u.id)}>{u.username}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
        </FilterBar>
      }
      batch={
        <BatchActionBar
          count={list.selectedKeys.length}
          onClear={list.clearSelection}
          running={batch.running}
          actions={[
            { key: 'enable', label: '批量启用', run: () => batch.run(() => batchApiKeys(list.selectedKeys, 'enable'), '已启用') },
            { key: 'disable', label: '批量禁用', confirm: `禁用选中的 ${list.selectedKeys.length} 个 Key？调用会立即被拒绝`, run: () => batch.run(() => batchApiKeys(list.selectedKeys, 'disable'), '已禁用') },
            { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个 Key？不可恢复`, run: () => batch.run(() => batchApiKeys(list.selectedKeys, 'delete'), '已删除') },
          ]}
        />
      }
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
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
      <ApiKeyForm
        open={formOpen}
        editing={editing}
        scopeOptions={scopeOptions}
        onClose={() => setFormOpen(false)}
        onSaved={() => { list.reload(); setCurrent(null) }}
        onCreated={setCreatedKey}
        ownerOptions={isAdmin ? (owners.data?.items ?? []).map((u) => ({ value: u.id, label: u.username })) : undefined}
      />
      <CreatedKeyModal value={createdKey} onClose={() => setCreatedKey(null)} />
      <ApiKeyDrawer apiKey={current} onClose={() => setCurrent(null)} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((k) => k.id === id)?.name} />
    </ListPage>
  )
}
