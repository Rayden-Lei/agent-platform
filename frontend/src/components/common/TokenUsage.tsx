import { Space, Tooltip, Typography } from 'antd'
import { formatCost, formatNumber } from '../../utils/format'

// Token 用量：紧凑版只显示总量（Tooltip 给拆分），完整版显示输入 / 输出 / 合计 / 成本。
interface Usage { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }
interface Props {
  usage?: Usage | null
  cost?: number | null
  compact?: boolean
}

export default function TokenUsage({ usage, cost, compact = false }: Props) {
  if (!usage || !usage.total_tokens) return <span style={{ color: '#9ca3af' }}>-</span>
  const detail = `输入 ${formatNumber(usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(usage.completion_tokens ?? 0)}`
  if (compact) {
    return <Tooltip title={detail + (cost !== null && cost !== undefined ? `，成本 ${formatCost(cost)}` : '')}><span>{formatNumber(usage.total_tokens)}</span></Tooltip>
  }
  return (
    <Space size={16} wrap>
      <span>输入 <Typography.Text strong>{formatNumber(usage.prompt_tokens ?? 0)}</Typography.Text></span>
      <span>输出 <Typography.Text strong>{formatNumber(usage.completion_tokens ?? 0)}</Typography.Text></span>
      <span>合计 <Typography.Text strong>{formatNumber(usage.total_tokens)}</Typography.Text></span>
      {cost !== null && cost !== undefined && <span>成本 <Typography.Text strong>{formatCost(cost)}</Typography.Text></span>}
    </Space>
  )
}
