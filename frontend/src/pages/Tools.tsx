import { useMemo, useState } from 'react'
import { Button, Select, Table, message } from 'antd'
import { PlusOutlined, ToolOutlined } from '@ant-design/icons'
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
  useOpenParam((id) => { const row = list.items.find((t) => t.id === id); if (row) setCurrent(row); else getTool(id).then(setCurrent).catch((e) => message.error(errorText(e, '工具不存在'))) })

  const onToggle = async (t: ToolRow) => { await toggleTool(t.id); list.reload() }
  const onDelete = async (t: ToolRow) => { try { await deleteTool(t.id); list.reload() } catch (e) { message.error(errorText(e, '删除失败')) } }
  const onEdit = (t: ToolRow) => { setEditing(t); setFormOpen(true) }
  const columns = useMemo(() => buildToolColumns({ sortProps: list.sortProps, canManage, onOpen: setCurrent, onToggle, onTest: setTesting, onEdit, onDelete }), [list.sortProps, canManage]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<ToolOutlined />} title="工具管理" description="内置工具与 HTTP 接口工具；参数声明决定模型如何结构化调用，停用后智能体与工作流都不再使用。" extra={canManage && <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>新增工具</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索名称 / 描述" />
          <Select allowClear placeholder="类型" style={{ width: 110 }} value={filters.type} onChange={(v) => setFilters({ type: v })} options={statusOptions('toolType')} />
          <Select allowClear placeholder="状态" style={{ width: 100 }} value={filters.is_enabled} onChange={(v) => setFilters({ is_enabled: v })} options={ENABLED_OPTIONS} />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchTools(list.selectedKeys, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${list.selectedKeys.length} 个工具？`, run: () => batch.run(() => batchTools(list.selectedKeys, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个工具？`, run: () => batch.run(() => batchTools(list.selectedKeys, 'delete'), '已删除') },
      ]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <ToolForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ToolTestModal tool={testing} onClose={() => setTesting(null)} />
      <ToolDrawer tool={current} canManage={canManage} onClose={() => setCurrent(null)} onTest={setTesting} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((t) => t.id === id)?.name} />
    </ListPage>
  )
}
