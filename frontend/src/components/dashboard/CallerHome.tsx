import { Card, Col, List, Row, Skeleton, Typography } from 'antd'
import { MessageOutlined, RobotOutlined } from '@ant-design/icons'
import type { AgentBrief, ConversationRow } from '../../api'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import { fromNow } from '../../utils/time'

// 调用者的工作台（docs/15 AG-05）：能对话的智能体卡片 + 本人最近的会话。调用者看不了运营统计，
// 此前工作台照样请求 /stats/* 拿 3 个 403、页面只剩横幅。数据由工作台页面取好传入，本组件不发请求。
interface Props {
  agents: AgentBrief[] | null // 只取第一页（OPTIONS_PAGE，100 个）
  agentsTotal?: number // 可对话智能体总数；超过已取的数量时提示去对话页搜索
  conversations: ConversationRow[] | null
  agentsError?: string | null
  conversationsError?: string | null
  onRetry: () => void
  onOpenAgent: (agent: AgentBrief) => void
  onOpenConversation: (conversation: ConversationRow) => void
}

export default function CallerHome({ agents, agentsTotal, conversations, agentsError, conversationsError, onRetry, onOpenAgent, onOpenConversation }: Props) {
  const total = agentsTotal ?? agents?.length
  const partial = !!agents && total !== undefined && total > agents.length
  return (
    <Row gutter={[12, 12]}>
      <Col xs={24} lg={16}>
        <Card size="small" title={`可以对话的智能体${total !== undefined ? `（${total}）` : ''}`}
          extra={partial ? <Typography.Text type="secondary" style={{ fontSize: 12 }}>这里显示前 {agents.length} 个，其余在对话页搜索</Typography.Text> : null}>
          {agentsError ? <ErrorState compact message={agentsError} onRetry={onRetry} /> : !agents ? <Skeleton active /> : agents.length === 0 ? (
            <EmptyState description="管理员还没有发布可用的智能体；发布后会出现在这里" />
          ) : (
            <Row gutter={[12, 12]}>
              {agents.map((a) => (
                <Col key={a.id} xs={24} sm={12} xl={8}>
                  <Card size="small" hoverable onClick={() => onOpenAgent(a)} style={{ height: '100%' }}>
                    <Typography.Text strong><RobotOutlined style={{ color: '#1e40af', marginRight: 6 }} />{a.name}</Typography.Text>
                    <Typography.Paragraph type="secondary" ellipsis={{ rows: 2 }} style={{ margin: '6px 0 0', fontSize: 13, minHeight: 40 }}>{a.description || '没有简介'}</Typography.Paragraph>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>{a.published_at ? `${fromNow(a.published_at)}发布` : ''}</Typography.Text>
                  </Card>
                </Col>
              ))}
            </Row>
          )}
        </Card>
      </Col>
      <Col xs={24} lg={8}>
        <Card size="small" title="最近的会话">
          {conversationsError ? <ErrorState compact message={conversationsError} onRetry={onRetry} /> : !conversations ? <Skeleton active /> : conversations.length === 0 ? (
            <EmptyState description="还没有会话；选一个智能体开始吧" />
          ) : (
            <List size="small" dataSource={conversations} renderItem={(c) => (
              <List.Item style={{ cursor: 'pointer' }} onClick={() => onOpenConversation(c)}>
                <List.Item.Meta avatar={<MessageOutlined style={{ color: '#9ca3af' }} />} title={c.title || '未命名会话'}
                  description={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{c.agent_name || '已删除的智能体'} · {fromNow(c.updated_at)}</Typography.Text>} />
              </List.Item>
            )} />
          )}
        </Card>
      </Col>
    </Row>
  )
}
