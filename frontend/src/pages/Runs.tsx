import { useMemo } from 'react'
import { Table } from 'antd'
import { HistoryOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { getRunsSummary, listRuns, type RunRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useAsyncData } from '../hooks/useAsyncData'
import { useQueryState } from '../hooks/useQueryState'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import EmptyState from '../components/common/EmptyState'
import RunFilters, { type RunFilterValues } from '../components/runs/RunFilters'
import RunStatCards from '../components/runs/RunStatCards'
import { buildRunColumns } from '../components/runs/runColumns'
import { useReview } from '../components/runs/useReview'
import { exportCsv } from '../utils/csv'
import { statusLabel } from '../constants/status'
import { formatDateTime } from '../utils/time'

const DEFAULTS: RunFilterValues = { run_type: undefined, status: undefined, source: undefined, agent_id: undefined, workflow_id: undefined, model_id: undefined, started_from: undefined, started_to: undefined }

// 运行记录页：筛选（同步到 URL）→ 统计卡随筛选联动（点卡即筛状态）→ 服务端排序的表格 → 行点击进详情页；待审核的行内直接通过 / 拒绝。
export default function Runs() {
  const navigate = useNavigate()
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const list = usePagedList<RunRow>(listRuns, {
    filters,
    defaultSort: { field: 'id', order: 'desc' },
    emptyText: <EmptyState description="当前筛选下没有运行记录。运行记录由对话、工作流运行与定时任务自动产生。" />,
  })
  // 统计不随 status 变化：状态卡本身就是按状态切分的
  const summaryFilters = useMemo(() => ({ ...filters, status: undefined }), [filters])
  const summary = useAsyncData(() => getRunsSummary(summaryFilters), [JSON.stringify(summaryFilters)], { errorText: '加载统计失败' })
  const { reviewing, review } = useReview(() => { list.reload(); summary.reload(true) })
  const columns = useMemo(() => buildRunColumns({ sortProps: list.sortProps, onReview: review, reviewing }), [list.sortProps, review, reviewing])

  const exportPage = () => exportCsv('运行记录', [
    { title: 'ID', value: (r: RunRow) => r.id },
    { title: '类型', value: (r) => statusLabel('runType', r.run_type) },
    { title: '状态', value: (r) => statusLabel('run', r.status) },
    { title: '归属', value: (r) => r.agent_name || r.workflow_name || '' },
    { title: '触发人', value: (r) => r.username || '' },
    { title: '来源', value: (r) => statusLabel('runSource', r.source) },
    { title: '模型', value: (r) => r.model_name || '' },
    { title: 'Token', value: (r) => r.token_usage?.total_tokens ?? '' },
    { title: '成本', value: (r) => r.cost ?? '' },
    { title: '耗时(ms)', value: (r) => r.latency_ms },
    { title: '开始时间', value: (r) => formatDateTime(r.started_at, '') },
    { title: '错误', value: (r) => r.error || '' },
  ], list.items)

  return (
    <ListPage
      header={<PageHeader icon={<HistoryOutlined />} title="运行记录" description="对话与工作流的每次运行留痕；统计随筛选联动，成本为各运行收尾时的快照合计。" />}
      stats={<RunStatCards summary={summary.data} loading={summary.loading && !summary.data} activeStatus={filters.status} onPickStatus={(status) => setFilters({ status })} />}
      filters={<RunFilters values={filters} onChange={setFilters} onReset={resetFilters} onRefresh={() => { list.reload(); summary.reload(true) }} onExport={exportPage} loading={list.loading} />}
    >
      <Table
        rowKey="id"
        {...list.tableProps}
        columns={columns}
        scroll={{ x: 'max-content' }}
        onRow={(r) => ({ onClick: () => navigate(`/runs/${r.id}`), style: { cursor: 'pointer' } })}
      />
    </ListPage>
  )
}
