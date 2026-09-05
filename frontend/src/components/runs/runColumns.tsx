import { Button, Space, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { CheckOutlined, CloseOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { RunRow } from '../../api'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import TokenUsage from '../common/TokenUsage'
import { formatCost } from '../../utils/format'
import { formatDuration } from '../../utils/time'

// 运行记录的列定义：全局运行记录页与详情页里的嵌入表共用；sortProps 来自 usePagedList，服务端排序。
interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  onReview?: (run: RunRow, decision: 'approved' | 'rejected') => void
  reviewing?: number | null
  hideOwner?: boolean // 详情页里已知归属，不重复显示
}

export function buildRunColumns({ sortProps, onReview, reviewing, hideOwner = false }: Options): ColumnsType<RunRow> {
  const columns: ColumnsType<RunRow> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80, ...sortProps('id'), render: (v: number) => <Link to={`/runs/${v}`}>#{v}</Link> },
    { title: '类型', dataIndex: 'run_type', width: 90, render: (v: string) => <StatusTag domain="runType" value={v} /> },
    { title: '状态', dataIndex: 'status', width: 110, render: (v: string) => <StatusTag domain="run" value={v} /> },
  ]
  if (!hideOwner) {
    columns.push({
      title: '归属', key: 'owner', width: 180, ellipsis: true,
      render: (_, r) => r.run_type === 'chat' ? <ResourceLink type="agent" id={r.agent_id} name={r.agent_name} /> : <ResourceLink type="workflow" id={r.workflow_id} name={r.workflow_name} />,
    })
  }
  columns.push(
    { title: '触发', key: 'source', width: 150, render: (_, r) => <Space size={4}><StatusTag domain="runSource" value={r.source} />{r.username && <span style={{ color: '#6b7280' }}>{r.username}</span>}</Space> },
    { title: '模型', dataIndex: 'model_name', width: 140, ellipsis: true, render: (v: string | null, r) => v ? <ResourceLink type="model" id={r.model_id} name={v} /> : '-' },
    { title: 'Token', key: 'tokens', width: 100, align: 'right', render: (_, r) => <TokenUsage usage={r.token_usage} cost={r.cost} compact /> },
    { title: '成本', dataIndex: 'cost', key: 'cost', width: 100, align: 'right', ...sortProps('cost'), render: (v: number | null) => formatCost(v) },
    { title: '耗时', dataIndex: 'latency_ms', key: 'latency_ms', width: 100, align: 'right', ...sortProps('latency_ms'), render: (v: number, r) => (r.finished_at ? formatDuration(v) : '-') },
    { title: '开始时间', dataIndex: 'started_at', key: 'started_at', width: 170, ...sortProps('started_at'), render: (v: string | null) => <TimeCell value={v} /> },
    { title: '错误', dataIndex: 'error', ellipsis: true, render: (v: string | null) => (v ? <Tooltip title={v}><span style={{ color: '#dc2626' }}>{v}</span></Tooltip> : '-') },
  )
  if (onReview) {
    columns.push({
      title: '操作', key: 'actions', width: 150, fixed: 'right',
      render: (_, r) => r.status === 'awaiting_review' ? (
        <Space size={4}>
          <Button size="small" type="primary" icon={<CheckOutlined />} loading={reviewing === r.id} onClick={(e) => { e.stopPropagation(); onReview(r, 'approved') }}>通过</Button>
          <Button size="small" danger icon={<CloseOutlined />} loading={reviewing === r.id} onClick={(e) => { e.stopPropagation(); onReview(r, 'rejected') }}>拒绝</Button>
        </Space>
      ) : <Link to={`/runs/${r.id}`}>详情</Link>,
    })
  }
  return columns
}
