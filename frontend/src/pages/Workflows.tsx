import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Network, Plus } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { batchWorkflows, deleteWorkflow, duplicateWorkflow, listWorkflows, publishWorkflow, type WorkflowRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import { statusOptions } from '../constants/status'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import RunWorkflowModal from '../components/workflows/RunWorkflowModal'
import WorkflowPublishModal from '../components/workflows/WorkflowPublishModal'
import { buildWorkflowColumns } from '../components/workflows/workflowColumns'
import DataTable from '../components/table/DataTable'
import Button from '../components/ui/Button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { errorText } from '../utils/errors'

type Filters = { q?: string; status?: string }
const DEFAULTS: Filters = { q: undefined, status: undefined }

// 工作流列表：筛选 / 排序 / 批量删除 / 复制 / 手动运行；节点构成、定时任务数与近 7 天运行随列表返回。
export default function Workflows() {
  const navigate = useNavigate()
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [running, setRunning] = useState<WorkflowRow | null>(null)
  const [publishing, setPublishing] = useState<WorkflowRow | null>(null)
  const list = usePagedList<WorkflowRow>(listWorkflows, { filters, selectable: true })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })

  const openCreate = () => navigate('/workflows/new')
  const remove = async (wf: WorkflowRow) => { try { await deleteWorkflow(wf.id); list.reload() } catch (e) { toast.error(errorText(e, '删除失败')) } }
  const duplicate = async (wf: WorkflowRow) => {
    try {
      const copy = await duplicateWorkflow(wf.id)
      toast.success(`已复制为「${copy.name}」`)
      list.reload()
    } catch (e) { toast.error(errorText(e, '复制失败')) }
  }
  // 发布：成功才关弹窗并刷新；与线上一致（unchanged）也刷新，让"未发布修改"标签消失
  const doPublish = async (note?: string) => {
    if (!publishing) return
    try {
      const r = await publishWorkflow(publishing.id, note)
      toast.success(r.publish_result === 'unchanged' ? '草稿与线上一致，无需发布' : `已发布，线上为 v${r.published_version}`)
      setPublishing(null)
      list.reload()
    } catch (e) { toast.error(errorText(e, '发布失败')); throw e }
  }
  const columns = useMemo(
    () => buildWorkflowColumns({ onRun: setRunning, onPublish: setPublishing, onDuplicate: duplicate, onDelete: remove }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  const empty = (
    <EmptyState
      description="还没有工作流。用画布把智能体、工具、条件与人工审核编排成流程，发布后可手动运行、作为对话目标、定时触发或被 API 调用。"
      action={{ label: '新建工作流', onClick: openCreate }}
    />
  )

  return (
    <ListPage
      header={
        <PageHeader
          icon={<Network />}
          title="工作流"
          description="节点编排的可执行流程。保存只改草稿；发布后才对外生效，可被运行、作为对话目标、挂定时任务或被 API 调用，每次发布生成一个可回滚的版本。"
          extra={<Button variant="primary" size="md" icon={<Plus />} onClick={openCreate}>新建工作流</Button>}
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}
          activeCount={Object.values(filters).filter(Boolean).length}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索工作流名称" />
          <Select value={filters.status ?? 'all'} onValueChange={(v) => setFilters({ status: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="状态">
              <SelectValue placeholder="状态" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              {statusOptions('workflow').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
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
            confirm: `删除选中的 ${list.selectedKeys.length} 个工作流？关联的定时任务会一并删除`,
            run: () => batch.run(() => batchWorkflows(list.selectedKeys), '已删除'),
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
      <RunWorkflowModal workflow={running} onClose={() => setRunning(null)} onDone={list.reload} />
      <WorkflowPublishModal
        target={publishing ? {
          name: publishing.name, draftVersion: publishing.version,
          publishedVersion: publishing.published_version, nodeCount: publishing.node_count,
        } : null}
        onClose={() => setPublishing(null)}
        onPublish={doPublish}
      />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((w) => w.id === id)?.name} />
    </ListPage>
  )
}
