import { useMemo, useState } from 'react'
import { Alert, Button, Select, Table, Tag, message } from 'antd'
import { ClockCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { batchSchedules, deleteSchedule, listSchedules, listWorkflows, OPTIONS_PAGE, runScheduleNow, toggleSchedule, type ScheduleRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { useOpenParam } from '../hooks/useOpenParam'
import { useAsyncData } from '../hooks/useAsyncData'
import { useSystemStatus } from '../hooks/useSystemStatus'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import ScheduleForm from '../components/admin/ScheduleForm'
import ScheduleDrawer from '../components/admin/ScheduleDrawer'
import { buildScheduleColumns } from '../components/admin/scheduleColumns'
import { errorText } from '../utils/errors'

type Filters = { q?: string; workflow_id?: string; is_enabled?: string }
const DEFAULTS: Filters = { q: undefined, workflow_id: undefined, is_enabled: undefined }
const ENABLED_OPTIONS = [{ value: 'true', label: '启用' }, { value: 'false', label: '停用' }]

// 定时任务：筛选 / 排序 / 启停开关 / 批量 / 立即运行 / 编辑 / 详情抽屉；页头显示调度器状态，未运行时给醒目提示。
export default function Schedules() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<ScheduleRow | null>(null)
  const [current, setCurrent] = useState<ScheduleRow | null>(null)
  const { status } = useSystemStatus()
  const scheduler = status?.scheduler
  const schedulerRunning = scheduler?.running ?? true // 状态未知时不误报
  const workflows = useAsyncData(() => listWorkflows(OPTIONS_PAGE), [])
  const list = usePagedList<ScheduleRow>(listSchedules, { filters, selectable: true, emptyText: <EmptyState description="还没有定时任务。选一个工作流、写好 cron，就能按计划自动运行。" action={{ label: '新建定时任务', onClick: () => { setEditing(null); setFormOpen(true) } }} /> })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => { const row = list.items.find((s) => s.id === id); if (row) setCurrent(row); else message.warning('该任务不在当前列表里') })

  const onToggle = async (s: ScheduleRow) => { await toggleSchedule(s.id); list.reload() }
  const onDelete = async (s: ScheduleRow) => { try { await deleteSchedule(s.id); list.reload(); setCurrent(null) } catch (e) { message.error(errorText(e, '删除失败')) } }
  const onRunNow = async (s: ScheduleRow) => { try { await runScheduleNow(s.id); message.success('已触发，稍后在运行记录里查看'); setTimeout(list.reload, 1500) } catch (e) { message.error(errorText(e, '触发失败')) } }
  const onEdit = (s: ScheduleRow) => { setEditing(s); setFormOpen(true) }
  const columns = useMemo(() => buildScheduleColumns({ sortProps: list.sortProps, schedulerRunning, onOpen: setCurrent, onToggle, onRunNow, onEdit, onDelete }), [list.sortProps, schedulerRunning]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<ClockCircleOutlined />} title="定时任务" description="按 cron 计划触发工作流；输入固定，运行记录来源标为「定时任务」。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>新建定时任务</Button>} />}
      alert={scheduler && !scheduler.running ? <Alert type="warning" showIcon message="调度器未运行，所有定时任务都不会触发" description={scheduler.reason || '请检查后端 SCHEDULER_ENABLED 配置或进程日志'} /> : undefined}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}
          extra={scheduler && <Tag color={scheduler.running ? 'success' : 'error'}>{scheduler.running ? `调度器运行中 · 已注册 ${scheduler.registered_jobs} / 启用 ${scheduler.enabled_jobs}` : '调度器未运行'}</Tag>}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索任务名称" />
          <Select allowClear showSearch optionFilterProp="label" placeholder="工作流" style={{ width: 170 }} value={filters.workflow_id} onChange={(v) => setFilters({ workflow_id: v })} options={(workflows.data?.items ?? []).map((w) => ({ value: String(w.id), label: w.name }))} />
          <Select allowClear placeholder="状态" style={{ width: 100 }} value={filters.is_enabled} onChange={(v) => setFilters({ is_enabled: v })} options={ENABLED_OPTIONS} />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[
        { key: 'enable', label: '批量启用', run: () => batch.run(() => batchSchedules(list.selectedKeys, 'enable'), '已启用') },
        { key: 'disable', label: '批量停用', confirm: `停用选中的 ${list.selectedKeys.length} 个任务？`, run: () => batch.run(() => batchSchedules(list.selectedKeys, 'disable'), '已停用') },
        { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个任务？`, run: () => batch.run(() => batchSchedules(list.selectedKeys, 'delete'), '已删除') },
      ]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <ScheduleForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ScheduleDrawer schedule={current} schedulerRunning={schedulerRunning} onClose={() => setCurrent(null)} onRunNow={onRunNow} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((s) => s.id === id)?.name} />
    </ListPage>
  )
}
