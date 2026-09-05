import { Alert, Descriptions, Typography } from 'antd'
import type { RunDetail } from '../../api'
import JsonView from '../common/JsonView'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TokenUsage from '../common/TokenUsage'
import { formatDateTime, formatDuration } from '../../utils/time'

// 运行详情概览：关键信息 + 输入 / 输出 + 错误 / 待审核中断信息。
interface Props { run: RunDetail }

export default function RunOverview({ run }: Props) {
  const interrupt = (run.output as { interrupt?: unknown } | null)?.interrupt
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {run.status === 'awaiting_review' && (
        <Alert type="warning" showIcon message="等待人工审核" description={<JsonView title="中断信息" value={interrupt} maxHeight={160} />} />
      )}
      {run.error && <Alert type="error" showIcon message="运行失败" description={<pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{run.error}</pre>} />}
      <Descriptions size="small" bordered column={{ xs: 1, md: 2 }} items={[
        { key: 'type', label: '类型', children: <StatusTag domain="runType" value={run.run_type} /> },
        { key: 'status', label: '状态', children: <StatusTag domain="run" value={run.status} /> },
        { key: 'owner', label: '归属', children: run.run_type === 'chat' ? <ResourceLink type="agent" id={run.agent_id} name={run.agent_name} showIcon /> : <ResourceLink type="workflow" id={run.workflow_id} name={run.workflow_name} showIcon /> },
        { key: 'source', label: '触发', children: <><StatusTag domain="runSource" value={run.source} /> {run.username && <span style={{ marginLeft: 6 }}>{run.username}</span>}{run.schedule_id && <span style={{ marginLeft: 6 }}><ResourceLink type="schedule" id={run.schedule_id} name={`定时任务 #${run.schedule_id}`} /></span>}</> },
        { key: 'model', label: '模型', children: run.model_id ? <ResourceLink type="model" id={run.model_id} name={run.model_name} /> : '-' },
        { key: 'conversation', label: '会话', children: run.conversation_id ? <ResourceLink type="conversation" id={run.conversation_id} name={`会话 #${run.conversation_id}`} /> : '-' },
        { key: 'started', label: '开始', children: formatDateTime(run.started_at) },
        { key: 'finished', label: '结束', children: formatDateTime(run.finished_at) },
        { key: 'latency', label: '耗时', children: run.finished_at ? formatDuration(run.latency_ms) : (run.status === 'running' || run.status === 'awaiting_review' ? '进行中' : '-') },
        { key: 'tokens', label: 'Token / 成本', children: <TokenUsage usage={run.token_usage} cost={run.cost} /> },
      ]} />
      <div>
        <Typography.Text strong>输入</Typography.Text>
        <JsonView value={run.input} maxHeight={220} />
      </div>
      <div>
        <Typography.Text strong>输出</Typography.Text>
        <JsonView value={run.output} maxHeight={320} />
      </div>
    </div>
  )
}
