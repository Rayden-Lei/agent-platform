import { Button, Descriptions, Drawer, Space, Typography } from 'antd'
import { PlayCircleOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { ScheduleRow } from '../../api'
import JsonView from '../common/JsonView'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import RunsTable from '../runs/RunsTable'
import { NextRunCell } from './scheduleColumns'

// 定时任务详情抽屉：计划与状态、固定输入、该工作流的定时触发运行记录；立即运行 / 编辑在头部。
interface Props { schedule: ScheduleRow | null; schedulerRunning: boolean; onClose: () => void; onRunNow: (s: ScheduleRow) => void; onEdit: (s: ScheduleRow) => void }

export default function ScheduleDrawer({ schedule: s, schedulerRunning, onClose, onRunNow, onEdit }: Props) {
  return (
    <Drawer title={s ? `定时任务：${s.name}` : ''} open={!!s} onClose={onClose} width={800} destroyOnHidden
      extra={s && <Space><Button icon={<PlayCircleOutlined />} onClick={() => onRunNow(s)}>立即运行</Button><Button type="primary" onClick={() => onEdit(s)}>编辑</Button></Space>}>
      {s && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Descriptions size="small" bordered column={2} items={[
            { key: 'wf', label: '工作流', children: <ResourceLink type="workflow" id={s.workflow_id} name={s.workflow_name || `#${s.workflow_id}`} showIcon /> },
            { key: 'status', label: '状态', children: <StatusTag domain="enabled" value={s.is_enabled} /> },
            { key: 'cron', label: 'Cron', children: <Space size={4}><Typography.Text code>{s.cron}</Typography.Text>{!s.cron_valid && <StatusTag domain="run" value="failed" style={{ display: 'none' }} />}{!s.cron_valid && <Typography.Text type="danger">非法表达式</Typography.Text>}</Space> },
            { key: 'next', label: '下次运行', children: <NextRunCell row={s} schedulerRunning={schedulerRunning} /> },
            { key: 'last', label: '最近运行', children: s.last_run_at ? <Space size={4}>{s.last_run_id && <Link to={`/runs/${s.last_run_id}`}>#{s.last_run_id}</Link>}<StatusTag domain="run" value={s.last_run_status} /><TimeCell value={s.last_run_at} /></Space> : '-' },
            { key: 'creator', label: '创建人', children: s.username || '-' },
            { key: 'created', label: '创建时间', span: 2, children: <TimeCell value={s.created_at} /> },
          ]} />
          <JsonView title="固定输入" value={s.input} maxHeight={200} />
          <div>
            <Typography.Text strong>定时触发的运行记录</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>该工作流所有来源为"定时任务"的运行</Typography.Text>
            <div style={{ marginTop: 8 }}><RunsTable filters={{ workflow_id: s.workflow_id, source: 'schedule' }} pageSize={5} /></div>
          </div>
        </div>
      )}
    </Drawer>
  )
}
