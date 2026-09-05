import { Badge, Card, List } from 'antd'
import { Link } from 'react-router-dom'
import type { StatsOverview } from '../../api'

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
    <Card size="small" title="待处理" loading={loading} styles={{ body: { padding: '4px 12px' } }}>
      <List
        size="small"
        dataSource={ITEMS}
        renderItem={(item) => {
          const count = pending?.[item.key] ?? 0
          return (
            <List.Item style={{ padding: '6px 0' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', width: '100%', alignItems: 'center', gap: 8 }}>
                <div style={{ minWidth: 0 }}>
                  {count > 0 ? <Link to={item.to}>{item.label}</Link> : <span style={{ color: '#9ca3af' }}>{item.label}</span>}
                  {item.hint && count > 0 && <div style={{ fontSize: 12, color: '#9ca3af' }}>{item.hint}</div>}
                </div>
                <Badge count={count} showZero color={count === 0 ? '#e5e7eb' : item.danger ? '#dc2626' : '#1e40af'} style={{ color: count === 0 ? '#9ca3af' : undefined }} />
              </div>
            </List.Item>
          )
        }}
      />
    </Card>
  )
}
