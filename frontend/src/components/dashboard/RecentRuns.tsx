import { Card, Table } from 'antd'
import { Link, useNavigate } from 'react-router-dom'
import type { RunRow } from '../../api'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { formatDuration } from '../../utils/time'

// 最近运行：紧凑表，点行进详情。
interface Props { runs: RunRow[]; loading: boolean }

export default function RecentRuns({ runs, loading }: Props) {
  const navigate = useNavigate()
  return (
    <Card size="small" title="最近运行" extra={<Link to="/runs">全部</Link>} loading={loading} styles={{ body: { padding: 0 } }}>
      <Table
        size="small"
        rowKey="id"
        dataSource={runs}
        pagination={false}
        onRow={(r) => ({ onClick: () => navigate(`/runs/${r.id}`), style: { cursor: 'pointer' } })}
        columns={[
          { title: '状态', dataIndex: 'status', width: 90, render: (v: string) => <StatusTag domain="run" value={v} /> },
          { title: '归属', key: 'owner', ellipsis: true, render: (_, r) => r.run_type === 'chat' ? <ResourceLink type="agent" id={r.agent_id} name={r.agent_name} /> : <ResourceLink type="workflow" id={r.workflow_id} name={r.workflow_name} /> },
          { title: '触发', dataIndex: 'source', width: 90, render: (v: string | null) => <StatusTag domain="runSource" value={v} /> },
          { title: '耗时', dataIndex: 'latency_ms', width: 80, align: 'right', render: (v: number, r) => (r.finished_at ? formatDuration(v) : '-') },
          { title: '时间', dataIndex: 'started_at', width: 100, render: (v: string | null) => <TimeCell value={v} mode="relative" /> },
        ]}
      />
    </Card>
  )
}
