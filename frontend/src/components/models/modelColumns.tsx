import { Button, Popconfirm, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { Link } from 'react-router-dom'
import type { ModelBreakerStatus, ModelRow, ModelUsageRow } from '../../api'
import EnableSwitch from '../common/EnableSwitch'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { formatCost, formatNumber } from '../../utils/format'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  breakers: Record<number, ModelBreakerStatus>
  usage: Record<number, ModelUsageRow>
  testingId: number | null
  canManage: boolean
  onOpen: (model: ModelRow) => void
  onToggle: (model: ModelRow) => Promise<unknown>
  onTest: (model: ModelRow) => void
  onEdit: (model: ModelRow) => void
  onDelete: (model: ModelRow) => void
}

// 熔断标签：open 显示重试倒计时，half_open 表示正在放行探测请求
export function BreakerTag({ breaker }: { breaker: ModelBreakerStatus | { state: string; consecutive_failures: number; retry_after_seconds: number } | null | undefined }) {
  if (!breaker || breaker.state === 'closed') return null
  return (
    <Tooltip title={`连续失败 ${breaker.consecutive_failures} 次；连通测试成功后立即恢复`}>
      <span><StatusTag domain="breaker" value={breaker.state} />{breaker.state === 'open' && <span style={{ fontSize: 12, color: '#9ca3af', marginLeft: 4 }}>{breaker.retry_after_seconds}s 后重试</span>}</span>
    </Tooltip>
  )
}

// 价格列：元 / 百万 token，未配置显示"-"并提示成本统计不可用
export function priceText(input: number | null, output: number | null): string {
  if (input === null && output === null) return '-'
  return `${input ?? '-'} / ${output ?? '-'}`
}

// 模型列表列定义：名称打开抽屉；状态列为启停开关 + 熔断标签；近 7 天用量来自 /stats/models。
export function buildModelColumns({ sortProps, breakers, usage, testingId, canManage, onOpen, onToggle, onTest, onEdit, onDelete }: Options): ColumnsType<ModelRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <a onClick={() => onOpen(r)}>{v}</a> },
    { title: '提供商', dataIndex: 'provider', key: 'provider', width: 110, ...sortProps('provider'), render: (v: string) => <StatusTag domain="provider" value={v} /> },
    { title: '模型名', dataIndex: 'model_name', ellipsis: true },
    {
      title: '价格（元 / 百万 token）', key: 'price', width: 170, align: 'right',
      render: (_, r) => (r.price_input === null && r.price_output === null ? <Tooltip title="未配置价格，运行成本按 0 计"><Tag color="warning">未配置</Tag></Tooltip> : priceText(r.price_input, r.price_output)),
    },
    {
      title: '状态', key: 'status', width: 190,
      render: (_, r) => <Space size={6}><EnableSwitch checked={r.is_enabled} disabled={!canManage} onToggle={() => onToggle(r)} /><BreakerTag breaker={breakers[r.id]} /></Space>,
    },
    { title: '智能体', dataIndex: 'agents_count', width: 80, align: 'right', render: (v: number, r) => (v ? <Link to={`/agents?model_id=${r.id}`}>{v}</Link> : '0') },
    {
      title: '近 7 天运行 / Token / 成本', key: 'usage', width: 210, align: 'right',
      render: (_, r) => { const u = usage[r.id]; return u && u.total ? `${u.total} / ${formatNumber(u.total_tokens)} / ${formatCost(u.cost)}` : '-' },
    },
    { title: '创建人', dataIndex: 'created_by_username', width: 100, render: (v: string | null) => v || '-' },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 170, ...sortProps('updated_at'), render: (v: string | null) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 200, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" loading={testingId === r.id} onClick={() => onTest(r)}>测试</Button>
          <Button size="small" disabled={!canManage} onClick={() => onEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？绑定了该模型的智能体将无法对话" onConfirm={() => onDelete(r)} disabled={!canManage}><Button size="small" danger disabled={!canManage}>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
