import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Clock, Plus, TriangleAlert } from 'lucide-react'
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
import DataTable from '../components/table/DataTable'
import Badge from '../components/ui/Badge'
import Button from '../components/ui/Button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
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
  const list = usePagedList<ScheduleRow>(listSchedules, { filters, selectable: true })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  useOpenParam((id) => {
    const row = list.items.find((s) => s.id === id)
    if (row) setCurrent(row)
    else toast.warning('该任务不在当前列表里')
  })

  const openCreate = () => { setEditing(null); setFormOpen(true) }
  const onToggle = async (s: ScheduleRow) => { await toggleSchedule(s.id); list.reload() }
  const onDelete = async (s: ScheduleRow) => {
    try { await deleteSchedule(s.id); list.reload(); setCurrent(null) } catch (e) { toast.error(errorText(e, '删除失败')) }
  }
  const onRunNow = async (s: ScheduleRow) => {
    try { await runScheduleNow(s.id); toast.success('已触发，稍后在运行记录里查看'); setTimeout(list.reload, 1500) } catch (e) { toast.error(errorText(e, '触发失败')) }
  }
  // 抽屉里点编辑：先关抽屉再开表单，避免抽屉叠抽屉
  const onEdit = (s: ScheduleRow) => { setCurrent(null); setEditing(s); setFormOpen(true) }
  const columns = useMemo(
    () => buildScheduleColumns({ schedulerRunning, onOpen: setCurrent, onToggle, onRunNow, onEdit, onDelete }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [schedulerRunning],
  )
  const empty = (
    <EmptyState description="还没有定时任务。选一个工作流、写好 cron，就能按计划自动运行。" action={{ label: '新建定时任务', onClick: openCreate }} />
  )

  return (
    <ListPage
      header={
        <PageHeader
          icon={<Clock />}
          title="定时任务"
          description="按 cron 计划触发工作流；输入固定，运行记录来源标为「定时任务」。"
          extra={<Button variant="primary" size="md" icon={<Plus />} onClick={openCreate}>新建定时任务</Button>}
        />
      }
      alert={scheduler && !scheduler.running ? (
        <div className="flex items-start gap-2 rounded-xl border border-[rgba(217,119,6,.35)] bg-[rgba(217,119,6,.10)] px-3.5 py-2.5">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-[#B45309]" />
          <div className="text-[13px]">
            <div className="font-medium">调度器未运行，所有定时任务都不会触发</div>
            <div className="text-muted-foreground">{scheduler.reason || '请检查后端 SCHEDULER_ENABLED 配置或进程日志'}</div>
          </div>
        </div>
      ) : undefined}
      filters={
        <FilterBar
          onReset={resetFilters}
          onRefresh={list.reload}
          loading={list.loading}
          extra={scheduler && (
            <Badge tone={scheduler.running ? 'success' : 'danger'}>
              {scheduler.running ? `调度器运行中 · 已注册 ${scheduler.registered_jobs} / 启用 ${scheduler.enabled_jobs}` : '调度器未运行'}
            </Badge>
          )}
        >
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索任务名称" />
          <Select value={filters.workflow_id ?? 'all'} onValueChange={(v) => setFilters({ workflow_id: v === 'all' ? undefined : v })}>
            <SelectTrigger className="h-8 w-[170px] text-[13px]" aria-label="工作流">
              <SelectValue placeholder="工作流" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部工作流</SelectItem>
              {(workflows.data?.items ?? []).map((w) => <SelectItem key={w.id} value={String(w.id)}>{w.name}</SelectItem>)}
            </SelectContent>
          </Select>
          <Select value={filters.is_enabled ?? 'all'} onValueChange={(v) => setFilters({ is_enabled: v === 'all' ? undefined : v })}>
            <SelectTrigger className="h-8 w-[100px] text-[13px]" aria-label="状态">
              <SelectValue placeholder="状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {ENABLED_OPTIONS.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </FilterBar>
      }
      batch={
        <BatchActionBar
          count={list.selectedKeys.length}
          onClear={list.clearSelection}
          running={batch.running}
          actions={[
            { key: 'enable', label: '批量启用', run: () => batch.run(() => batchSchedules(list.selectedKeys, 'enable'), '已启用') },
            { key: 'disable', label: '批量停用', confirm: `停用选中的 ${list.selectedKeys.length} 个任务？`, run: () => batch.run(() => batchSchedules(list.selectedKeys, 'disable'), '已停用') },
            { key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个任务？`, run: () => batch.run(() => batchSchedules(list.selectedKeys, 'delete'), '已删除') },
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
      <ScheduleForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={() => { list.reload(); setCurrent(null) }} />
      <ScheduleDrawer schedule={current} schedulerRunning={schedulerRunning} onClose={() => setCurrent(null)} onRunNow={onRunNow} onEdit={onEdit} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((s) => s.id === id)?.name} />
    </ListPage>
  )
}
