import { Table, Typography } from 'antd'
import type { RunNodeRow } from '../../api'
import { NODE_TYPE_LABEL } from '../../constants/status'
import ChartCard from '../charts/ChartCard'
import StackedBar from '../charts/StackedBar'
import JsonView from '../common/JsonView'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { formatDuration } from '../../utils/time'

// 工作流运行的节点日志：耗时占比图 + 逐节点表（展开看输入输出快照）。并行分支的节点顺序按日志写入顺序。
interface Props { nodes: RunNodeRow[] }

export default function NodeLogTable({ nodes }: Props) {
  if (!nodes.length) return <Typography.Text type="secondary">这次运行没有节点日志（对话类运行不产生节点日志）。</Typography.Text>
  const durations = nodes.filter((n) => n.duration_ms !== null).map((n) => ({ x: `${n.node_id}（${NODE_TYPE_LABEL[n.node_type] ?? n.node_type}）`, value: n.duration_ms ?? 0 }))
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {durations.length > 1 && (
        <ChartCard title="各节点耗时（毫秒）" height={Math.max(160, 28 * durations.length + 60)}>
          <StackedBar data={durations} horizontal height={Math.max(136, 28 * durations.length + 36)} />
        </ChartCard>
      )}
      <Table
        size="small"
        rowKey="id"
        dataSource={nodes}
        pagination={false}
        columns={[
          { title: '节点', dataIndex: 'node_id', width: 160 },
          { title: '类型', dataIndex: 'node_type', width: 110, render: (v: string) => NODE_TYPE_LABEL[v] ?? v },
          { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => <StatusTag domain="nodeStatus" value={v} /> },
          { title: '耗时', dataIndex: 'duration_ms', width: 100, align: 'right', render: (v: number | null) => formatDuration(v) },
          { title: '开始', dataIndex: 'started_at', width: 170, render: (v: string | null) => <TimeCell value={v} /> },
          { title: '错误', dataIndex: 'error', ellipsis: true, render: (v: string | null) => (v ? <span style={{ color: '#dc2626' }}>{v}</span> : '-') },
        ]}
        expandable={{
          expandedRowRender: (n) => (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <JsonView title="输入（截断 500 字符）" value={n.input} maxHeight={200} />
              <JsonView title="输出（截断 500 字符）" value={n.output} maxHeight={200} />
            </div>
          ),
        }}
      />
    </div>
  )
}
