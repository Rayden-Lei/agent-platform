import { lazy, Suspense, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { WorkflowDetail } from '../../api'
import Badge from '../ui/Badge'
import EmptyState from '../common/EmptyState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { paletteOf } from '../../pages/workflow/palette'

// 画布预览依赖 @xyflow（独立 chunk），按需加载，列表与其他页签不背这个体积
const GraphPreview = lazy(() => import('../../pages/workflow/GraphPreview'))

// 工作流概览页签：基本信息 + 节点构成 + 只读画布 + 定时任务 + 引用它的智能体。
interface Props { workflow: WorkflowDetail }

function Panel({ title, extra, children }: { title: ReactNode; extra?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <h3 className="m-0 text-[13.5px] font-semibold">{title}</h3>
        {extra}
      </div>
      <div className="px-4 py-3">{children}</div>
    </section>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 gap-3 py-1">
      <span className="w-20 shrink-0 text-[12.5px] text-muted-foreground">{label}</span>
      <span className="min-w-0 flex-1 text-[13.5px]">{children}</span>
    </div>
  )
}

export default function WorkflowOverview({ workflow: wf }: Props) {
  const nodeTypes = Object.entries(wf.node_types || {})
  return (
    <div className="flex flex-col gap-3">
      <section className="rounded-xl border border-border bg-card px-4 py-3">
        <Row label="描述">{wf.description || <span className="text-muted-foreground">-</span>}</Row>
        <Row label="节点构成">
          {nodeTypes.length ? (
            <span className="inline-flex flex-wrap gap-1">
              {nodeTypes.map(([t, n]) => <Badge key={t} tone="neutral">{paletteOf(t)?.label ?? t} × {n}</Badge>)}
            </span>
          ) : <Badge tone="neutral">空图</Badge>}
        </Row>
        <div className="mt-1 grid grid-cols-1 gap-x-6 sm:grid-cols-2 lg:grid-cols-3">
          <Row label="连线">{wf.graph?.edges?.length ?? 0}</Row>
          <Row label="版本">v{wf.version}</Row>
          <Row label="创建人">{wf.created_by_username || '-'}</Row>
          <Row label="创建时间"><TimeCell value={wf.created_at} /></Row>
          <Row label="更新时间"><TimeCell value={wf.updated_at} /></Row>
          <Row label="最近运行"><TimeCell value={wf.last_run_at} mode="relative" /></Row>
        </div>
      </section>

      <Panel title="流程图" extra={<Link to={`/workflows/${wf.id}/edit`} className="text-[13px] text-primary hover:underline">去编辑</Link>}>
        {wf.node_count ? (
          <Suspense fallback={<Skeleton className="h-56 w-full" />}><GraphPreview graph={wf.graph} /></Suspense>
        ) : <EmptyState description="画布是空的，去编辑器拖入节点" />}
      </Panel>

      <Panel title={`定时任务（${wf.schedules.length}）`}>
        {wf.schedules.length ? (
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {wf.schedules.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2 text-[13.5px]">
                <ResourceLink type="schedule" id={s.id} name={s.name} showIcon />
                <code className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[12.5px]">{s.cron}</code>
                <StatusTag domain="enabled" value={s.is_enabled} />
                <span className="text-[12px] text-muted-foreground">最近触发 <TimeCell value={s.last_run_at} mode="relative" /></span>
              </li>
            ))}
          </ul>
        ) : <span className="text-[13px] text-muted-foreground">没有定时任务；到"定时任务"页新建并选择本工作流。</span>}
      </Panel>

      <Panel title={`引用它的智能体（${wf.agents.length}）`}>
        {wf.agents.length ? (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
            {wf.agents.map((a) => (
              <li key={a.id} className="flex items-center gap-2 text-[13.5px]">
                <ResourceLink type="agent" id={a.id} name={a.name} showIcon />
                <StatusTag domain="agent" value={a.status} />
              </li>
            ))}
          </ul>
        ) : <span className="text-[13px] text-muted-foreground">没有智能体关联本工作流；在智能体表单里选择即可让对话走这个流程。</span>}
      </Panel>
    </div>
  )
}
