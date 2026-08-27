import { useEffect, useState } from 'react'
import { Card, Col, Row, Statistic, Typography, Button, Space } from 'antd'
import { RobotOutlined, ThunderboltOutlined, PartitionOutlined, DatabaseOutlined, PlusOutlined, MessageOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { listAgents, listModels, listWorkflows, listKBs } from '../api'

export default function Dashboard() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [stats, setStats] = useState({ agents: 0, models: 0, workflows: 0, kbs: 0 })

  useEffect(() => {
    Promise.all([listAgents(), listModels(), listWorkflows(), listKBs()])
      .then(([a, m, w, k]: any) => setStats({ agents: a.length, models: m.length, workflows: w.length, kbs: k.length }))
      .catch(() => {})
  }, [])

  const cards = [
    { title: '智能体', value: stats.agents, icon: <RobotOutlined />, color: '#1e40af', path: '/agents' },
    { title: '模型', value: stats.models, icon: <ThunderboltOutlined />, color: '#0e7490', path: '/models' },
    { title: '工作流', value: stats.workflows, icon: <PartitionOutlined />, color: '#b45309', path: '/workflows' },
    { title: '知识库', value: stats.kbs, icon: <DatabaseOutlined />, color: '#15803d', path: '/knowledge-bases' },
  ]

  const quickActions = [
    { label: '创建智能体', icon: <PlusOutlined />, path: '/agents' },
    { label: '新建工作流', icon: <PartitionOutlined />, path: '/workflows/new' },
    { label: '开始对话', icon: <MessageOutlined />, path: '/chat' },
  ]

  return (
    <div>
      <div className="dash-banner">
        <div style={{ position: 'relative', zIndex: 1 }}>
          <Typography.Title level={3} style={{ color: '#fff', margin: '0 0 8px' }}>
            欢迎回来，{user?.username}
          </Typography.Title>
          <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.85)', marginBottom: 20, fontSize: 14 }}>
            统一管理你的智能体、模型、工作流与知识库，快速构建 AI 应用。
          </Typography.Paragraph>
          <Space wrap>
            {quickActions.map((a) => (
              <Button key={a.label} ghost icon={a.icon} onClick={() => navigate(a.path)}>{a.label}</Button>
            ))}
          </Space>
        </div>
      </div>

      <Row gutter={[16, 16]}>
        {cards.map((c) => (
          <Col xs={12} md={6} key={c.title}>
            <Card className="tech-card" onClick={() => navigate(c.path)} style={{ cursor: 'pointer' }} styles={{ body: { padding: 20 } }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
                <div className="stat-icon" style={{ background: c.color }}>{c.icon}</div>
                <Statistic title={c.title} value={c.value} />
              </div>
            </Card>
          </Col>
        ))}
      </Row>
    </div>
  )
}
