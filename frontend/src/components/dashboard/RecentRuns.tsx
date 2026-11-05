import { Link, useNavigate } from 'react-router-dom'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { RunRow } from '../../api'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { formatDuration } from '../../utils/time'

// 最近运行：紧凑表，点行进详情。固定 5 行、无分页，用原生 table。
interface Props { runs: RunRow[]; loading: boolean }

const COLUMNS: { label: string; width?: number; align?: 'right' }[] = [
  { label: '状态', width: 90 },
  { label: '归属' },
  { label: '触发', width: 90 },
  { label: '耗时', width: 80, align: 'right' },
  { label: '时间', width: 100 },
]

export default function RecentRuns({ runs, loading }: Props) {
  const navigate = useNavigate()
  return (
    <section className="flex h-full flex-col rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">最近运行</h3>
        <Link to="/runs" className="text-[12.5px] text-primary hover:underline">全部</Link>
      </div>

      {/* 窄屏横向滚动：五列固定宽合计 360px，320px 屏上装不下。
          原来外层是 overflow-hidden，最后两列被直接裁掉、也滑不出来 —— 改成可横向滚动。
          行高与列宽保持不变，只是允许滑动。 */}
      <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
        <table className="w-full min-w-[360px] border-collapse text-[13.5px]">
          <thead className="bg-secondary">
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.label}
                  className="px-3 py-2 text-[12.5px] font-medium text-muted-foreground"
                  style={{ width: c.width, textAlign: c.align ?? 'left' }}
                >
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && [0, 1, 2, 3, 4].map((i) => (
              <tr key={i} className="border-t border-border">
                {COLUMNS.map((c) => <td key={c.label} className="px-3 py-2.5"><Skeleton className="h-3.5 w-full" /></td>)}
              </tr>
            ))}
            {!loading && runs.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={COLUMNS.length} className="px-3 py-6 text-center text-[12.5px] text-muted-foreground">还没有运行记录</td>
              </tr>
            )}
            {!loading && runs.map((r) => (
              <tr
                key={r.id}
                className="cursor-pointer border-t border-border transition-colors hover:bg-accent/50"
                onClick={() => navigate(`/runs/${r.id}`)}
              >
                <td className="px-3 py-2.5"><StatusTag domain="run" value={r.status} /></td>
                <td className="max-w-0 truncate px-3 py-2.5">
                  {r.run_type === 'chat'
                    ? <ResourceLink type="agent" id={r.agent_id} name={r.agent_name} />
                    : <ResourceLink type="workflow" id={r.workflow_id} name={r.workflow_name} />}
                </td>
                <td className="px-3 py-2.5"><StatusTag domain="runSource" value={r.source} /></td>
                <td className="px-3 py-2.5 text-right">{r.finished_at ? formatDuration(r.latency_ms) : '-'}</td>
                <td className="px-3 py-2.5"><TimeCell value={r.started_at} mode="relative" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}
