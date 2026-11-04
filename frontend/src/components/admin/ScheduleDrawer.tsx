import type { ReactNode } from 'react'
import { Play } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ScheduleRow } from '../../api'
import JsonView from '../common/JsonView'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import RunsTable from '../runs/RunsTable'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { NextRunCell } from './scheduleColumns'

// 定时任务详情抽屉：计划与状态、固定输入、该工作流的定时触发运行记录；立即运行 / 编辑在头部。
interface Props { schedule: ScheduleRow | null; schedulerRunning: boolean; onClose: () => void; onRunNow: (s: ScheduleRow) => void; onEdit: (s: ScheduleRow) => void }

// 详情字段：标签在上、值在下（替代 antd Descriptions 的表格块）
function Field({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? 'col-span-2' : undefined}>
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      <dd className="m-0 mt-1 text-[13px] text-foreground">{children}</dd>
    </div>
  )
}

export default function ScheduleDrawer({ schedule: s, schedulerRunning, onClose, onRunNow, onEdit }: Props) {
  return (
    <Drawer
      open={!!s}
      width={720}
      title={s ? `定时任务：${s.name}` : ''}
      onClose={onClose}
      extra={s && (
        <>
          <Button icon={<Play className="size-3.5" />} onClick={() => onRunNow(s)}>立即运行</Button>
          <Button variant="primary" onClick={() => onEdit(s)}>编辑</Button>
        </>
      )}
    >
      {s && (
        <div className="flex flex-col gap-4">
          <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-border bg-card p-3.5">
            <Field label="工作流"><ResourceLink type="workflow" id={s.workflow_id} name={s.workflow_name || `#${s.workflow_id}`} showIcon /></Field>
            <Field label="状态"><StatusTag domain="enabled" value={s.is_enabled} /></Field>
            <Field label="Cron">
              <span className="inline-flex items-center gap-1.5">
                <code className="font-mono text-[12.5px]">{s.cron}</code>
                {!s.cron_valid && <span className="text-[12.5px] text-destructive">非法表达式</span>}
              </span>
            </Field>
            <Field label="下次运行"><NextRunCell row={s} schedulerRunning={schedulerRunning} /></Field>
            <Field label="最近运行">
              {s.last_run_at ? (
                <span className="inline-flex items-center gap-1.5">
                  {s.last_run_id && <Link to={`/runs/${s.last_run_id}`} className="text-primary hover:underline">#{s.last_run_id}</Link>}
                  <StatusTag domain="run" value={s.last_run_status} />
                  <TimeCell value={s.last_run_at} />
                </span>
              ) : '-'}
            </Field>
            <Field label="创建人">{s.username || '-'}</Field>
            <Field label="创建时间" wide><TimeCell value={s.created_at} /></Field>
          </dl>

          <JsonView title="固定输入" value={s.input} maxHeight={200} />

          <section className="flex flex-col gap-2">
            <h3 className="m-0 text-[13px] font-semibold text-foreground">
              定时触发的运行记录
              <span className="ml-2 text-[12px] font-normal text-muted-foreground">该工作流所有来源为"定时任务"的运行</span>
            </h3>
            <RunsTable filters={{ workflow_id: s.workflow_id, source: 'schedule' }} pageSize={5} />
          </section>
        </div>
      )}
    </Drawer>
  )
}
