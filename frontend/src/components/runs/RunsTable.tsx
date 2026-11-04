import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { listRuns, type RunRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
import DataTable from '../table/DataTable'
import { buildRunColumns } from './runColumns'
import { useReview } from './useReview'

// 详情页里的嵌入运行记录表：固定归属（agent_id / workflow_id）由 filters 传入；行内可审核；普通分页。
interface Props {
  filters: Record<string, string | number | boolean | undefined>
  hideOwner?: boolean
  pageSize?: number
}

export default function RunsTable({ filters, hideOwner = true, pageSize = 10 }: Props) {
  const navigate = useNavigate()
  const list = usePagedList<RunRow>(listRuns, { filters, pageSize, defaultSort: { field: 'id', order: 'desc' } })
  const { reviewing, review } = useReview(list.reload)
  const columns = useMemo(
    () => buildRunColumns({ onReview: review, reviewing, hideOwner }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [review, reviewing, hideOwner],
  )
  return (
    <DataTable
      columns={columns}
      rows={list.items}
      rowKey={(r) => r.id}
      loading={list.loading}
      error={list.error}
      empty={<EmptyState description="还没有运行记录" />}
      onRetry={list.reload}
      page={list.page}
      pageSize={list.pageSize}
      total={list.total}
      onPageChange={list.load}
      sort={list.sort}
      onSortChange={list.setSort}
      onRowClick={(r) => navigate(`/runs/${r.id}`)}
    />
  )
}
