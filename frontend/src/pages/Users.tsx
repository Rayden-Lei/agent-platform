import { useMemo, useState } from 'react'
import { Button, Select, Table, message } from 'antd'
import { PlusOutlined, TeamOutlined } from '@ant-design/icons'
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
  useOpenParam((id) => { const row = list.items.find((u) => u.id === id); if (row) setCurrent(row); else message.warning('该用户不在当前列表里，请调整筛选') })

  const onToggle = async (u: UserRow) => { await updateUser(u.id, { is_active: !u.is_active }); list.reload() }
  const onDelete = async (u: UserRow) => { try { await deleteUser(u.id); list.reload() } catch (e) { message.error(errorText(e, '删除失败')) } }
  const onEdit = (u: UserRow) => { setEditing(u); setFormOpen(true) }
  const selectedOthers = list.selectedKeys.filter((id) => id !== meId)
  const columns = useMemo(() => buildUserColumns({ sortProps: list.sortProps, meId, onOpen: setCurrent, onToggle, onEdit, onResetPassword: setResetting, onDelete }), [list.sortProps, meId]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<TeamOutlined />} title="用户管理" description="账号、角色与启停；开发者可管理资源，调用者只能对话。对自己的账号不能停用、降级或删除。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增用户</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索用户名" />
          <Select allowClear placeholder="角色" style={{ width: 110 }} value={filters.role} onChange={(v) => setFilters({ role: v })} options={statusOptions('role')} />
          <Select allowClear placeholder="状态" style={{ width: 100 }} value={filters.is_active} onChange={(v) => setFilters({ is_active: v })} options={ACTIVE_OPTIONS} />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchUsers(selectedOthers, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${selectedOthers.length} 个用户？（自动跳过自己）`, run: () => batch.run(() => batchUsers(selectedOthers, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${selectedOthers.length} 个用户？（自动跳过自己）`, run: () => batch.run(() => batchUsers(selectedOthers, 'delete'), '已删除') },
      ]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <UserForm open={formOpen} editing={editing} meId={meId} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ResetPasswordModal user={resetting} onClose={() => setResetting(null)} />
      <UserDrawer user={current} onClose={() => setCurrent(null)} onEdit={onEdit} onResetPassword={setResetting} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((u) => u.id === id)?.username} />
    </ListPage>
  )
}
