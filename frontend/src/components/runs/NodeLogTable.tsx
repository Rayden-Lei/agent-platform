import type { RunNodeRow } from '../../api'
import { NODE_TYPE_LABEL } from '../../constants/status'
import ChartCard from '../charts/ChartCard'
import StackedBar from '../charts/StackedBar'
import JsonView from '../common/JsonView'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import DataTable, { type DataColumn } from '../table/DataTable'
import { formatDuration } from '../../utils/time'

// 工作流运行的节点日志：耗时占比图 + 逐节点表（展开看输入输出快照）。并行分支的节点顺序按日志写入顺序。
interface Props { nodes: RunNodeRow[] }

export default function NodeLogTable({ nodes }: Props) {
  if (!nodes.length) {
    return <span className="text-[13.5px] text-muted-foreground">这次运行没有节点日志（对话类运行不产生节点日志）。</span>
  }
  const durations = nodes.filter((n) => n.duration_ms !== null).map((n) => ({ x: `${n.node_id}（${NODE_TYPE_LABEL[n.node_type] ?? n.node_type}）`, value: n.duration_ms ?? 0 }))
  const columns: DataColumn<RunNodeRow>[] = [
    { key: 'node_id', header: '节点', primary: true, width: 160, cell: (n) => <span className="font-medium">{n.node_id}</span> },
    { key: 'node_type', header: '类型', width: 110, hideOnMobile: true, cell: (n) => NODE_TYPE_LABEL[n.node_type] ?? n.node_type },
    { key: 'status', header: '状态', width: 100, cell: (n) => <StatusTag domain="nodeStatus" value={n.status} /> },
    { key: 'duration_ms', header: '耗时', width: 100, align: 'right', cell: (n) => formatDuration(n.duration_ms) },
    { key: 'started_at', header: '开始', width: 170, hideOnMobile: true, cell: (n) => <TimeCell value={n.started_at} /> },
    {
      key: 'error', header: '错误', hideOnMobile: true,
      cell: (n) => (n.error ? <span className="block truncate text-destructive">{n.error}</span> : '-'),
    },
  ]
  return (
    <div className="flex flex-col gap-3">
      {durations.length > 1 && (
        <ChartCard title="各节点耗时（毫秒）" height={Math.max(160, 28 * durations.length + 60)}>
          <StackedBar data={durations} horizontal height={Math.max(136, 28 * durations.length + 36)} />
        </ChartCard>
      )}
      <DataTable
        columns={columns}
        rows={nodes}
        rowKey={(n) => n.id}
        expand={{
          expandable: () => true,
          render: (n) => (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <JsonView title="输入（截断 500 字符）" value={n.input} maxHeight={200} />
              <JsonView title="输出（截断 500 字符）" value={n.output} maxHeight={200} />
            </div>
          ),
        }}
      />
    </div>
  )
}
