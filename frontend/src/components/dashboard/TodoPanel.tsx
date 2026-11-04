import { Link } from 'react-router-dom'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { StatsOverview } from '../../api'
import Badge from '../ui/Badge'

// 待处理面板：把概览里的 pending 计数变成可点的入口，零值置灰。
interface Props { pending: StatsOverview['pending'] | null; loading: boolean }

const ITEMS: { key: keyof StatsOverview['pending']; label: string; to: string; danger?: boolean; hint: string }[] = [
  { key: 'awaiting_review', label: '待人工审核的运行', to: '/runs?status=awaiting_review', hint: '工作流在人工审核节点暂停，等你通过或拒绝' },
  { key: 'failed_today', label: '今日失败的运行', to: '/runs?status=failed', danger: true, hint: '点开看错误原因与节点日志' },
  { key: 'stuck_running', label: '疑似卡住的运行', to: '/runs?status=running', danger: true, hint: '超过 1 小时仍是运行中，通常是进程重启后没收尾' },
  { key: 'running', label: '进行中的运行', to: '/runs?status=running', hint: '' },
  { key: 'failed_documents', label: '解析失败的文档', to: '/knowledge-bases', danger: true, hint: '到知识库详情里看失败原因并重新解析' },
  { key: 'processing_documents', label: '处理中的文档', to: '/knowledge-bases', hint: '' },
  { key: 'open_breakers', label: '熔断中的模型', to: '/models', danger: true, hint: '模型连续失败被熔断，连通测试成功即恢复' },
  { key: 'unregistered_schedules', label: '未注册的定时任务', to: '/schedules', danger: true, hint: '启用但没进调度器，通常是 cron 非法' },
]

export default function TodoPanel({ pending, loading }: Props) {
  return (
    <section className="flex h-full flex-col rounded-xl border border-border bg-card">
      <div className="border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">待处理</h3>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-3 py-1">
        {loading
          ? ITEMS.map((item) => (
              <div key={item.key} className="flex items-center justify-between gap-2 py-2">
                <Skeleton className="h-3.5 w-32" />
                <Skeleton className="h-4 w-7 rounded-full" />
              </div>
            ))
          : ITEMS.map((item) => {
              const count = pending?.[item.key] ?? 0
              return (
                <div key={item.key} className="flex items-center justify-between gap-2 py-1.5">
                  <div className="min-w-0">
                    {count > 0
                      ? <Link to={item.to} className="text-[13.5px] text-primary hover:underline">{item.label}</Link>
                      : <span className="text-[13.5px] text-muted-foreground">{item.label}</span>}
                    {item.hint && count > 0 && <div className="text-[12px] leading-snug text-muted-foreground">{item.hint}</div>}
                  </div>
                  <Badge tone={count === 0 ? 'neutral' : item.danger ? 'danger' : 'accent'}>{count}</Badge>
                </div>
              )
            })}
      </div>
    </section>
  )
}
