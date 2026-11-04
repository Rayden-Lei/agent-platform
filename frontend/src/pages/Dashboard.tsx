import { useState } from 'react'
import { MessageSquare, Plus, Network, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { getDailyRunStats, getModelUsage, getStatsOverview, listAvailableAgents, listConversations, OPTIONS_PAGE } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import ErrorState from '../components/common/ErrorState'
import Button from '../components/ui/Button'
import KpiCards from '../components/dashboard/KpiCards'
import TrendSection from '../components/dashboard/TrendSection'
import ConsumptionSection from '../components/dashboard/ConsumptionSection'
import TodoPanel from '../components/dashboard/TodoPanel'
import RecentRuns from '../components/dashboard/RecentRuns'
import ResourceSummary from '../components/dashboard/ResourceSummary'
import CallerHome from '../components/dashboard/CallerHome'

// 工作台：横幅与快捷入口 → 今日指标（环比）→ 运行趋势与状态分布 → 待处理与最近运行 → 模型消耗 → 资源概览。
// 整页可滚是 docs/07 第 1 节的唯一例外；数据来自 /stats/overview、/stats/runs/daily、/stats/models。
export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [days, setDays] = useState(7)
  const isManager = user?.role === 'admin' || user?.role === 'developer'
  // 运营统计只对 admin / developer 开放；调用者不请求（此前照样发 3 个 /stats 请求拿 403），改看可对话的智能体与最近会话
  const overview = useAsyncData(() => getStatsOverview(), [], { auto: isManager, errorText: '加载工作台概览失败' })
  const daily = useAsyncData(() => getDailyRunStats({ days }), [days], { auto: isManager, errorText: '加载运行趋势失败' })
  const models = useAsyncData(() => getModelUsage({ days }), [days], { auto: isManager, errorText: '加载模型用量失败' })
  const callerAgents = useAsyncData(() => listAvailableAgents(OPTIONS_PAGE), [], { auto: !isManager, errorText: '加载智能体失败' })
  const recent = useAsyncData(() => listConversations({ page: 1, page_size: 5 }), [], { auto: !isManager, errorText: '加载最近会话失败' })

  const quickActions = [
    { label: '创建智能体', icon: <Plus />, path: '/agents/new' },
    { label: '新建工作流', icon: <Network />, path: '/workflows/new' },
    { label: '上传文档', icon: <Upload />, path: '/knowledge-bases' },
    { label: '开始对话', icon: <MessageSquare />, path: '/chat' },
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto pr-0.5">
      <div className="dash-banner">
        <div className="relative z-[1]">
          <h1 className="m-0 mb-1.5 text-[20px] font-semibold text-white">欢迎回来，{user?.username}</h1>
          <p className="m-0 mb-4 text-[14px] leading-relaxed text-white/85">
            {isManager ? '这里汇总今天的运行、消耗与待处理事项；点击卡片可进入对应列表。' : '选择一个已发布的智能体开始对话。'}
          </p>
          <div className="flex flex-wrap gap-2">
            {quickActions.filter((a) => isManager || a.path === '/chat').map((a) => (
              <Button
                key={a.label}
                size="sm"
                icon={a.icon}
                onClick={() => navigate(a.path)}
                className="border-white/35 bg-white/10 text-white hover:bg-white/20"
              >
                {a.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {!isManager ? (
        <CallerHome agents={callerAgents.data?.items ?? null} agentsTotal={callerAgents.data?.total} conversations={recent.data?.items ?? null}
          agentsError={callerAgents.error} conversationsError={recent.error} onRetry={() => { callerAgents.reload(); recent.reload() }}
          onOpenAgent={(a) => navigate(`/chat?agent=${a.id}`)}
          onOpenConversation={(c) => navigate(`/chat?${c.agent_id ? `agent=${c.agent_id}&` : ''}conversation=${c.id}`)} />
      ) : overview.error ? (
        <ErrorState message={overview.error} onRetry={() => overview.reload()} />
      ) : (
        <>
          <KpiCards today={overview.data?.today ?? null} daily={daily.data?.items ?? []} loading={overview.loading && !overview.data} onGo={navigate} />
          <TrendSection daily={daily.data?.items ?? []} days={days} onDaysChange={setDays} loading={daily.loading && !daily.data} error={daily.error} onRetry={() => daily.reload()} />
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
            <TodoPanel pending={overview.data?.pending ?? null} loading={overview.loading && !overview.data} />
            <div className="lg:col-span-2"><RecentRuns runs={overview.data?.recent_runs ?? []} loading={overview.loading && !overview.data} /></div>
          </div>
          <ConsumptionSection models={models.data?.items ?? []} daily={daily.data?.items ?? []} loading={models.loading && !models.data} error={models.error} onRetry={() => models.reload()} />
          <ResourceSummary resources={overview.data?.resources ?? null} loading={overview.loading && !overview.data} onGo={navigate} />
        </>
      )}
    </div>
  )
}
