import { useState } from 'react'
import { Button, Descriptions, Drawer, Segmented, Space, Tag, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { getModel, getModelUsage, type ModelBreakerStatus, type ModelRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import ErrorState from '../common/ErrorState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import StatCards from '../layout/StatCards'
import { formatCost, formatNumber, formatPercent } from '../../utils/format'
import { formatDuration } from '../../utils/time'
import { BreakerTag, priceText } from './modelColumns'

// 模型详情抽屉：配置信息、熔断状态、区间用量（来自 /stats/models）、绑定它的智能体；测试 / 编辑在抽屉头部。
interface Props {
  model: ModelRow | null
  breaker?: ModelBreakerStatus
  testing: boolean
  canManage: boolean
  onClose: () => void
  onTest: (model: ModelRow) => void
  onEdit: (model: ModelRow) => void
}

export default function ModelDrawer({ model, breaker, testing, canManage, onClose, onTest, onEdit }: Props) {
  const [days, setDays] = useState(7)
  const id = model?.id ?? 0
  const detail = useAsyncData(() => getModel(id), [id], { auto: !!model, errorText: '加载模型详情失败' })
  const usage = useAsyncData(async () => (await getModelUsage({ days, model_id: id })).items[0] ?? null, [id, days], { auto: !!model })
  const u = usage.data
  return (
    <Drawer title={model ? `模型：${model.name}` : ''} open={!!model} onClose={onClose} width={720} destroyOnHidden
      extra={model && <Space><Button loading={testing} onClick={() => onTest(model)}>连通测试</Button><Button type="primary" disabled={!canManage} onClick={() => onEdit(model)}>编辑</Button></Space>}>
      {model && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Descriptions size="small" bordered column={2} items={[
            { key: 'status', label: '状态', children: <Space size={6}><StatusTag domain="enabled" value={model.is_enabled} /><BreakerTag breaker={breaker} />{!breaker && <Typography.Text type="secondary" style={{ fontSize: 12 }}>熔断器正常</Typography.Text>}</Space> },
            { key: 'provider', label: '提供商', children: <StatusTag domain="provider" value={model.provider} /> },
            { key: 'model_name', label: '模型名', children: <Typography.Text copyable>{model.model_name}</Typography.Text> },
            { key: 'api_base', label: 'API 地址', children: <Typography.Text copyable ellipsis style={{ maxWidth: 260 }}>{model.api_base}</Typography.Text> },
            { key: 'price', label: '价格（元 / 百万 token）', children: priceText(model.price_input, model.price_output) },
            { key: 'params', label: '默认参数', children: Object.keys(model.default_params || {}).length ? <Typography.Text code>{JSON.stringify(model.default_params)}</Typography.Text> : '-' },
            { key: 'creator', label: '创建人', children: model.created_by_username || '-' },
            { key: 'updated', label: '更新时间', children: <TimeCell value={model.updated_at} /> },
          ]} />
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <Space size={8}><Typography.Text strong>用量统计</Typography.Text><Link to={`/runs?model_id=${model.id}`} style={{ fontSize: 12 }}>查看运行记录</Link></Space>
              <Segmented size="small" value={days} onChange={(v) => setDays(Number(v))} options={[{ label: '近 7 天', value: 7 }, { label: '近 30 天', value: 30 }]} />
            </div>
            {usage.error ? <ErrorState compact message={usage.error} onRetry={() => usage.reload()} /> : (
              <StatCards cols={3} loading={usage.loading && !u} items={[
                { key: 'total', title: '运行次数', value: u?.total ?? 0, hint: u ? `成功 ${u.success} · 失败 ${u.failed}` : undefined },
                { key: 'rate', title: '成功率', value: formatPercent(u?.success_rate ?? null) },
                { key: 'latency', title: '平均耗时', value: formatDuration(u?.avg_latency_ms ?? null) },
                { key: 'tokens', title: 'Token', value: formatNumber(u?.total_tokens ?? 0), hint: u ? `输入 ${formatNumber(u.prompt_tokens)} · 输出 ${formatNumber(u.completion_tokens)}` : undefined },
                { key: 'cost', title: '成本', value: formatCost(u?.cost ?? 0), hint: '按运行时快照的单价计算' },
                { key: 'agents', title: '绑定智能体', value: model.agents_count },
              ]} />
            )}
          </div>
          <div>
            <Typography.Text strong>使用该模型的智能体（{model.agents_count}）</Typography.Text>
            <div style={{ marginTop: 8 }}>
              {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : detail.data?.agents.length ? (
                <Space direction="vertical" size={4}>
                  {detail.data.agents.map((a) => <span key={a.id}><ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} /></span>)}
                </Space>
              ) : <Typography.Text type="secondary">{detail.loading ? '加载中…' : '没有智能体使用该模型'}</Typography.Text>}
            </div>
          </div>
          {!model.is_enabled && <Tag color="warning">已停用：绑定它的智能体对话会被拒绝，启用后恢复</Tag>}
        </div>
      )}
    </Drawer>
  )
}
