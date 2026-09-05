import { useState } from 'react'
import { Button, Col, Row, Space, Typography } from 'antd'
import { MessageOutlined, PartitionOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { getDailyRunStats, getModelUsage, getStatsOverview } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import ErrorState from '../components/common/ErrorState'
import KpiCards from '../components/dashboard/KpiCards'
import TrendSection from '../components/dashboard/TrendSection'
import ConsumptionSection from '../components/dashboard/ConsumptionSection'
import TodoPanel from '../components/dashboard/TodoPanel'
import RecentRuns from '../components/dashboard/RecentRuns'
import ResourceSummary from '../components/dashboard/ResourceSummary'

// 工作台：横幅与快捷入口 → 今日指标（环比）→ 运行趋势与状态分布 → 待处理与最近运行 → 模型消耗 → 资源概览。
// 整页可滚是 docs/07 第 1 节的唯一例外；数据来自 /stats/overview、/stats/runs/daily、/stats/models。
export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [days, setDays] = useState(7)
  const overview = useAsyncData(() => getStatsOverview(), [], { errorText: '加载工作台概览失败' })
  const daily = useAsyncData(() => getDailyRunStats({ days }), [days], { errorText: '加载运行趋势失败' })
  const models = useAsyncData(() => getModelUsage({ days }), [days], { errorText: '加载模型用量失败' })
  const isManager = user?.role === 'admin' || user?.role === 'developer'

  const quickActions = [
    { label: '创建智能体', icon: <PlusOutlined />, path: '/agents' },
    { label: '新建工作流', icon: <PartitionOutlined />, path: '/workflows/new' },
    { label: '上传文档', icon: <UploadOutlined />, path: '/knowledge-bases' },
    { label: '开始对话', icon: <MessageOutlined />, path: '/chat' },
  ]

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 12, paddingRight: 2 }}>
      <div className="dash-banner">
        <div style={{ position: 'relative', zIndex: 1 }}>
          <Typography.Title level={3} style={{ color: '#fff', margin: '0 0 6px' }}>欢迎回来，{user?.username}</Typography.Title>
          <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.85)', marginBottom: 16, fontSize: 14 }}>
            {isManager ? '这里汇总今天的运行、消耗与待处理事项；点击卡片可进入对应列表。' : '选择一个已发布的智能体开始对话。'}
          </Typography.Paragraph>
          <Space wrap>
            {quickActions.filter((a) => isManager || a.path === '/chat').map((a) => (
              <Button key={a.label} ghost icon={a.icon} onClick={() => navigate(a.path)}>{a.label}</Button>
            ))}
          </Space>
        </div>
      </div>

      {!isManager ? null : overview.error ? (
        <ErrorState message={overview.error} onRetry={() => overview.reload()} />
      ) : (
        <>
          <KpiCards today={overview.data?.today ?? null} daily={daily.data?.items ?? []} loading={overview.loading && !overview.data} onGo={navigate} />
          <TrendSection daily={daily.data?.items ?? []} days={days} onDaysChange={setDays} loading={daily.loading && !daily.data} error={daily.error} onRetry={() => daily.reload()} />
          <Row gutter={[12, 12]}>
            <Col xs={24} lg={8}><TodoPanel pending={overview.data?.pending ?? null} loading={overview.loading && !overview.data} /></Col>
            <Col xs={24} lg={16}><RecentRuns runs={overview.data?.recent_runs ?? []} loading={overview.loading && !overview.data} /></Col>
          </Row>
          <ConsumptionSection models={models.data?.items ?? []} daily={daily.data?.items ?? []} loading={models.loading && !models.data} error={models.error} onRetry={() => models.reload()} />
          <ResourceSummary resources={overview.data?.resources ?? null} loading={overview.loading && !overview.data} onGo={navigate} />
        </>
      )}
    </div>
  )
}
