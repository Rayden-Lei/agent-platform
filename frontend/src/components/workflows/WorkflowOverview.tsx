import { lazy, Suspense } from 'react'
import { Card, Descriptions, Skeleton, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import type { WorkflowDetail } from '../../api'
import EmptyState from '../common/EmptyState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { paletteOf } from '../../pages/workflow/palette'

// 画布预览依赖 @xyflow（独立 chunk），按需加载，列表与其他页签不背这个体积
const GraphPreview = lazy(() => import('../../pages/workflow/GraphPreview'))

// 工作流概览页签：基本信息 + 节点构成 + 只读画布 + 定时任务 + 引用它的智能体。
interface Props { workflow: WorkflowDetail }

export default function WorkflowOverview({ workflow: wf }: Props) {
  const nodeTypes = Object.entries(wf.node_types || {})
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Descriptions size="small" bordered column={4} items={[
        { key: 'desc', label: '描述', span: 4, children: wf.description || '-' },
        { key: 'nodes', label: '节点构成', span: 2, children: nodeTypes.length ? <Space size={4} wrap>{nodeTypes.map(([t, n]) => <Tag key={t}>{paletteOf(t)?.label ?? t} × {n}</Tag>)}</Space> : <Tag>空图</Tag> },
        { key: 'edges', label: '连线', children: wf.graph?.edges?.length ?? 0 },
        { key: 'version', label: '版本', children: `v${wf.version}` },
        { key: 'creator', label: '创建人', children: wf.created_by_username || '-' },
        { key: 'created', label: '创建时间', children: <TimeCell value={wf.created_at} /> },
        { key: 'updated', label: '更新时间', children: <TimeCell value={wf.updated_at} /> },
        { key: 'last_run', label: '最近运行', children: <TimeCell value={wf.last_run_at} mode="relative" /> },
      ]} />
      <Card size="small" title="流程图" extra={<Link to={`/workflows/${wf.id}/edit`}>去编辑</Link>}>
        {wf.node_count ? <Suspense fallback={<Skeleton active paragraph={{ rows: 6 }} />}><GraphPreview graph={wf.graph} /></Suspense> : <EmptyState description="画布是空的，去编辑器拖入节点" />}
      </Card>
      <Card size="small" title={`定时任务（${wf.schedules.length}）`}>
        {wf.schedules.length ? (
          <Space direction="vertical" size={4}>
            {wf.schedules.map((s) => (
              <span key={s.id}>
                <ResourceLink type="schedule" id={s.id} name={s.name} showIcon />　<Typography.Text code>{s.cron}</Typography.Text>　<StatusTag domain="enabled" value={s.is_enabled} />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>最近触发 <TimeCell value={s.last_run_at} mode="relative" /></Typography.Text>
              </span>
            ))}
          </Space>
        ) : <Typography.Text type="secondary">没有定时任务；到"定时任务"页新建并选择本工作流。</Typography.Text>}
      </Card>
      <Card size="small" title={`引用它的智能体（${wf.agents.length}）`}>
        {wf.agents.length ? (
          <Space direction="vertical" size={4}>
            {wf.agents.map((a) => <span key={a.id}><ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} /></span>)}
          </Space>
        ) : <Typography.Text type="secondary">没有智能体关联本工作流；在智能体表单里选择即可让对话走这个流程。</Typography.Text>}
      </Card>
    </div>
  )
}
