import { Collapse, Space, Tag, Typography } from 'antd'
import type { TraceStep } from '../../api'
import JsonView from '../common/JsonView'
import { formatDuration } from '../../utils/time'

// 调用链步骤列表（docs/15 3.4）：按发生顺序列出改写 / 检索 / 模型调用 / 工具执行，展开看入参与结果。
// 装配页调试的"详情"在用；第 2 批运行详情的"调用链"页签（OP-08）沿用同一组件与同一结构。
export const STEP_TYPE_LABEL: Record<string, { text: string; color: string }> = {
  rewrite: { text: '改写', color: 'purple' },
  retrieve: { text: '检索', color: 'blue' },
  llm: { text: '模型', color: 'geekblue' },
  tool: { text: '工具', color: 'orange' },
}
const STATUS_LABEL: Record<string, { text: string; color: string }> = {
  error: { text: '失败', color: 'error' },
  denied: { text: '无权检索', color: 'warning' },
}

function stepSummary(step: TraceStep): string {
  const m = step.meta || {}
  if (step.type === 'retrieve') return `候选 ${m.candidate_count ?? 0} · 返回 ${m.returned ?? 0}${m.acl_rejected ? ` · 鉴权剔除 ${m.acl_rejected}` : ''}`
  if (step.type === 'llm') {
    const usage = m.usage?.total_tokens ? ` · Token ${m.usage.total_tokens}` : ''
    const tools = step.output?.tool_calls?.length ? ` · 请求工具 ${step.output.tool_calls.join('、')}` : ''
    return `${m.first_token_ms != null ? `首字 ${formatDuration(m.first_token_ms)}` : '无文本输出'}${usage}${tools}`
  }
  return ''
}

export default function TraceStepList({ steps }: { steps: TraceStep[] }) {
  if (!steps.length) return <Typography.Text type="secondary">这一轮没有记录到调用步骤</Typography.Text>
  return (
    <Collapse size="small" items={steps.map((step, i) => {
      const type = STEP_TYPE_LABEL[step.type] ?? { text: step.type, color: 'default' }
      const status = STATUS_LABEL[step.status]
      return {
        key: step.id || String(i),
        label: (
          <Space size={8} wrap>
            <Tag color={type.color}>{type.text}</Tag>
            <Typography.Text strong>{step.name}</Typography.Text>
            {status && <Tag color={status.color}>{status.text}</Tag>}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{formatDuration(step.duration_ms)}{stepSummary(step) ? ` · ${stepSummary(step)}` : ''}</Typography.Text>
          </Space>
        ),
        children: (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <JsonView title="入参" value={step.input} maxHeight={240} />
            <JsonView title="结果" value={step.output} maxHeight={240} />
            <div style={{ gridColumn: '1 / -1' }}><JsonView title="明细" value={step.meta} maxHeight={200} /></div>
          </div>
        ),
      }
    })} />
  )
}
