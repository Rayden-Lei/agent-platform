import { useMemo, useState } from 'react'
import { Button, Select, Table, message } from 'antd'
import { ApartmentOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { batchWorkflows, deleteWorkflow, duplicateWorkflow, listWorkflows, type WorkflowRow } from '../api'
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
import { buildWorkflowColumns } from '../components/workflows/workflowColumns'
import { errorText } from '../utils/errors'

type Filters = { q?: string; status?: string }
const DEFAULTS: Filters = { q: undefined, status: undefined }

// 工作流列表：筛选 / 排序 / 批量删除 / 复制 / 手动运行；节点构成、定时任务数与近 7 天运行随列表返回。
export default function Workflows() {
  const navigate = useNavigate()
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [running, setRunning] = useState<WorkflowRow | null>(null)
  const list = usePagedList<WorkflowRow>(listWorkflows, {
    filters,
    selectable: true,
    emptyText: <EmptyState description="还没有工作流。用画布把智能体、工具、条件与人工审核编排成流程，可手动运行、定时触发或被智能体调用。" action={{ label: '新建工作流', onClick: () => navigate('/workflows/new') }} />,
  })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  const remove = async (wf: WorkflowRow) => { try { await deleteWorkflow(wf.id); list.reload() } catch (e) { message.error(errorText(e, '删除失败')) } }
  const duplicate = async (wf: WorkflowRow) => {
    try { const copy = await duplicateWorkflow(wf.id); message.success(`已复制为「${copy.name}」`); list.reload() } catch (e) { message.error(errorText(e, '复制失败')) }
  }
  const columns = useMemo(() => buildWorkflowColumns({ sortProps: list.sortProps, onRun: setRunning, onDuplicate: duplicate, onDelete: remove }), [list.sortProps]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<ApartmentOutlined />} title="工作流" description="节点编排的可执行流程；发布后可被定时任务、智能体与 API 调用。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/workflows/new')}>新建工作流</Button>} />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索工作流名称" />
          <Select allowClear placeholder="状态" style={{ width: 110 }} value={filters.status} onChange={(v) => setFilters({ status: v })} options={statusOptions('workflow')} />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[{ key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个工作流？关联的定时任务会一并删除`, run: () => batch.run(() => batchWorkflows(list.selectedKeys), '已删除') }]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <RunWorkflowModal workflow={running} onClose={() => setRunning(null)} onDone={list.reload} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((w) => w.id === id)?.name} />
    </ListPage>
  )
}
