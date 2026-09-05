import { useMemo, useState } from 'react'
import { Button, Select, Table, message } from 'antd'
import { KeyOutlined, PlusOutlined } from '@ant-design/icons'
import { batchApiKeys, deleteApiKey, listApiKeys, listUsers, OPTIONS_PAGE, toggleApiKey, type ApiKeyRow } from '../api'
import { useAuth } from '../store/auth'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import { useAsyncData } from '../hooks/useAsyncData'
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
  const list = usePagedList<ApiKeyRow>(listApiKeys, { filters, selectable: true, emptyText: <EmptyState description="还没有 API Key。生成后外部系统可用它调用对话与工作流接口。" action={{ label: '生成 Key', onClick: () => { setEditing(null); setFormOpen(true) } }} /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => { const row = list.items.find((k) => k.id === id); if (row) setCurrent(row); else message.warning('该 Key 不在当前列表里') })

  const onToggle = async (k: ApiKeyRow) => { await toggleApiKey(k.id); list.reload() }
  const onDelete = async (k: ApiKeyRow) => { try { await deleteApiKey(k.id); list.reload() } catch (e) { message.error(errorText(e, '删除失败')) } }
  const onEdit = (k: ApiKeyRow) => { setEditing(k); setFormOpen(true) }
  const columns = useMemo(() => buildApiKeyColumns({ sortProps: list.sortProps, isAdmin, onOpen: setCurrent, onToggle, onEdit, onDelete }), [list.sortProps, isAdmin]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<KeyOutlined />} title="API Key 管理" description="外部调用凭据：配额、来源白名单与限速；明文只在生成时显示一次。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>生成 Key</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称" />
          <Select allowClear placeholder="状态" style={{ width: 100 }} value={filters.is_enabled} onChange={(v) => setFilters({ is_enabled: v })} options={ENABLED_OPTIONS} />
          {isAdmin && <Select allowClear showSearch optionFilterProp="label" placeholder="归属" style={{ width: 150 }} value={filters.user_id} onChange={(v) => setFilters({ user_id: v })} options={(owners.data?.items ?? []).map((u) => ({ value: String(u.id), label: u.username }))} />}
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchApiKeys(list.selectedKeys, 'enable'), '已启用') },
        { key: 'disable', label: '批量禁用', confirm: `禁用选中的 ${list.selectedKeys.length} 个 Key？调用会立即被拒绝`, run: () => batch.run(() => batchApiKeys(list.selectedKeys, 'disable'), '已禁用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个 Key？不可恢复`, run: () => batch.run(() => batchApiKeys(list.selectedKeys, 'delete'), '已删除') },
      ]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <ApiKeyForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} onCreated={setCreatedKey} />
      <CreatedKeyModal value={createdKey} onClose={() => setCreatedKey(null)} />
      <ApiKeyDrawer apiKey={current} onClose={() => setCurrent(null)} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((k) => k.id === id)?.name} />
    </ListPage>
  )
}
