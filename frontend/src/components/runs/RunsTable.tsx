import { useMemo } from 'react'
import { Table } from 'antd'
import { useNavigate } from 'react-router-dom'
import { listRuns, type RunRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
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
  const list = usePagedList<RunRow>(listRuns, { filters, pageSize, defaultSort: { field: 'id', order: 'desc' }, emptyText: <EmptyState description="还没有运行记录" /> })
  const { reviewing, review } = useReview(list.reload)
  const columns = useMemo(() => buildRunColumns({ sortProps: list.sortProps, onReview: review, reviewing, hideOwner }), [list.sortProps, review, reviewing, hideOwner])
  return (
    <Table
      rowKey="id"
      size="small"
      {...list.tableProps}
      columns={columns}
      scroll={{ x: 'max-content' }}
      onRow={(r) => ({ onClick: () => navigate(`/runs/${r.id}`), style: { cursor: 'pointer' } })}
    />
  )
}
