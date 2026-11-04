import { useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { Copy } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger } from '@/components/shadcn/tabs'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
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

// 配置信息的一行：左侧固定宽度标签，右侧值允许换行
function Field({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[150px_1fr] items-start gap-3 border-b border-border px-3 py-2 last:border-b-0">
      <span className="text-[12.5px] leading-5 text-muted-foreground">{label}</span>
      <span className="min-w-0 text-[13px] leading-5 text-foreground">{children}</span>
    </div>
  )
}

export default function ModelDrawer({ model, breaker, testing, canManage, onClose, onTest, onEdit }: Props) {
  const [days, setDays] = useState(7)
  const id = model?.id ?? 0
  const detail = useAsyncData(() => getModel(id), [id], { auto: !!model, errorText: '加载模型详情失败' })
  const usage = useAsyncData(async () => (await getModelUsage({ days, model_id: id })).items[0] ?? null, [id, days], { auto: !!model })
  const u = usage.data
  // 密钥类 / 地址这类长串要能复制走，省得手抄
  const copy = (text: string) => { navigator.clipboard?.writeText(text).then(() => toast.success('已复制')) }
  const otherParams = Object.fromEntries(Object.entries(model?.default_params || {}).filter(([k]) => k !== 'thinking'))
  return (
    <Drawer
      open={!!model}
      onClose={onClose}
      width={720}
      title={model ? `模型：${model.name}` : ''}
      extra={model && (
        <>
          <Button size="sm" variant="secondary" disabled={testing} onClick={() => onTest(model)}>{testing ? '测试中…' : '连通测试'}</Button>
          <Button size="sm" variant="primary" disabled={!canManage} onClick={() => onEdit(model)}>编辑</Button>
        </>
      )}
    >
      {model && (
        <div className="flex flex-col gap-4">
          <div className="overflow-hidden rounded-lg border border-border">
            <Field label="状态">
              <span className="inline-flex flex-wrap items-center gap-1.5">
                <StatusTag domain="enabled" value={model.is_enabled} />
                <BreakerTag breaker={breaker} />
                {!breaker && <span className="text-[12px] text-muted-foreground">熔断器正常</span>}
              </span>
            </Field>
            <Field label="提供商"><StatusTag domain="provider" value={model.provider} /></Field>
            <Field label="模型名">
              <span className="inline-flex items-center gap-1">
                <span className="break-all font-mono text-[12.5px]">{model.model_name}</span>
                <Button size="sm" variant="ghost" aria-label="复制模型名" onClick={() => copy(model.model_name)}><Copy className="size-3.5" /></Button>
              </span>
            </Field>
            <Field label="API 地址">
              <span className="inline-flex items-start gap-1">
                <span className="break-all font-mono text-[12.5px]">{model.api_base}</span>
                <Button size="sm" variant="ghost" aria-label="复制 API 地址" onClick={() => copy(model.api_base)}><Copy className="size-3.5" /></Button>
              </span>
            </Field>
            <Field label="价格（元 / 百万 token）">{priceText(model.price_input, model.price_output)}</Field>
            <Field label="思考模式">
              {model.default_params?.thinking
                ? <StatusTag domain="thinking" value={String(model.default_params.thinking)} />
                : <span className="text-muted-foreground">跟随模型默认</span>}
            </Field>
            <Field label="其他默认参数">
              {Object.keys(otherParams).length
                ? <code className="break-all rounded bg-secondary px-1.5 py-0.5 text-[12.5px]">{JSON.stringify(otherParams)}</code>
                : '-'}
            </Field>
            <Field label="创建人">{model.created_by_username || '-'}</Field>
            <Field label="更新时间"><TimeCell value={model.updated_at} /></Field>
          </div>

          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="inline-flex items-center gap-2">
                <span className="text-[13px] font-medium text-foreground">用量统计</span>
                <Link to={`/runs?model_id=${model.id}`} className="text-[12px] text-primary hover:underline">查看运行记录</Link>
              </span>
              <Tabs value={String(days)} onValueChange={(v) => setDays(Number(v))}>
                <TabsList className="h-7">
                  <TabsTrigger value="7" className="text-[12px]">近 7 天</TabsTrigger>
                  <TabsTrigger value="30" className="text-[12px]">近 30 天</TabsTrigger>
                </TabsList>
              </Tabs>
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

          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium text-foreground">使用该模型的智能体（{model.agents_count}）</span>
            {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : detail.data?.agents.length ? (
              <div className="flex flex-col gap-1">
                {detail.data.agents.map((a) => (
                  <span key={a.id} className="inline-flex items-center gap-1.5">
                    <ResourceLink type="agent" id={a.id} name={a.name} showIcon />
                    <StatusTag domain="agent" value={a.status} />
                  </span>
                ))}
              </div>
            ) : <span className="text-[13px] text-muted-foreground">{detail.loading ? '加载中…' : '没有智能体使用该模型'}</span>}
          </div>

          {!model.is_enabled && <Badge tone="warning">已停用：绑定它的智能体对话会被拒绝，启用后恢复</Badge>}
        </div>
      )}
    </Drawer>
  )
}
