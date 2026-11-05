import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Plus, Users as UsersIcon } from 'lucide-react'
import { batchUsers, deleteUser, listUsers, updateUser, type UserRow } from '../api'
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
import UserForm from '../components/admin/UserForm'
import ResetPasswordModal from '../components/admin/ResetPasswordModal'
import UserDrawer from '../components/admin/UserDrawer'
import { buildUserColumns } from '../components/admin/userColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { errorText } from '../utils/errors'

type Filters = { q?: string; role?: string; is_active?: string }
const DEFAULTS: Filters = { q: undefined, role: undefined, is_active: undefined }
const ACTIVE_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }]

// 用户管理（仅管理员）：筛选 / 排序 / 启停开关 / 批量启停删除 / 改角色 / 重置密码 / 详情抽屉（含最近审计）。
export default function Users() {
  const meId = useAuth((s) => s.user?.id as number | undefined)
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [resetting, setResetting] = useState<UserRow | null>(null)
  const [current, setCurrent] = useState<UserRow | null>(null)
  const list = usePagedList<UserRow>(listUsers, { filters, selectable: true, emptyText: <EmptyState description="没有匹配的用户" /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => { const row = list.items.find((u) => u.id === id); if (row) setCurrent(row); else toast.warning('该用户不在当前列表里，请调整筛选') })

  const onToggle = async (u: UserRow) => { await updateUser(u.id, { is_active: !u.is_active }); list.reload() }
  const onDelete = async (u: UserRow) => { try { await deleteUser(u.id); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) } }
  const onEdit = (u: UserRow) => { setEditing(u); setFormOpen(true) }
  const selectedOthers = list.selectedKeys.filter((id) => id !== meId)
  const columns = useMemo(() => buildUserColumns({ meId, onOpen: setCurrent, onToggle, onEdit, onResetPassword: setResetting, onDelete }), [meId]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<UsersIcon />} title="用户管理" description="账号、角色与启停；开发者可管理资源，调用者只能对话。对自己的账号不能停用、降级或删除。" extra={<Button variant="primary" size="md" icon={<Plus />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增用户</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索用户名" />
          <Select value={filters.role ?? 'all'} onValueChange={(v) => setFilters({ role: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="角色"><SelectValue placeholder="角色" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部角色</SelectItem>
              {statusOptions('role').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.is_active ?? 'all'} onValueChange={(v) => setFilters({ is_active: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[100px] text-[13px]" aria-label="状态"><SelectValue placeholder="状态" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {ACTIVE_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchUsers(selectedOthers, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${selectedOthers.length} 个用户？（自动跳过自己）`, run: () => batch.run(() => batchUsers(selectedOthers, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${selectedOthers.length} 个用户？（自动跳过自己）`, run: () => batch.run(() => batchUsers(selectedOthers, 'delete'), '已删除') },
      ]} />}
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        loading={list.loading}
        error={list.error}
        empty={<EmptyState description="没有匹配的用户" />}
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
      <UserForm open={formOpen} editing={editing} meId={meId} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} onSaved={list.reload} />
      <UserDrawer user={current} onClose={() => setCurrent(null)} onEdit={onEdit} onResetPassword={setResetting} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((u) => u.id === id)?.username} />
    </ListPage>
  )
}
