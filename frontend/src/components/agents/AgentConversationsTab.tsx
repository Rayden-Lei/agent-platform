import { Table, Tooltip } from 'antd'
import { Link } from 'react-router-dom'
import { listConversations, type ConversationRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
import TimeCell from '../common/TimeCell'

// 智能体详情的会话页签：只列当前登录用户与该智能体的会话（会话按用户行级隔离），可跳到对话页继续。
interface Props { agentId: number }

export default function AgentConversationsTab({ agentId }: Props) {
  const list = usePagedList<ConversationRow>(listConversations, { filters: { agent_id: agentId }, pageSize: 10, emptyText: <EmptyState description="你还没有与该智能体的会话" /> })
  return (
    <Table
      size="small"
      rowKey="id"
      {...list.tableProps}
      columns={[
        { title: '标题', dataIndex: 'title', ellipsis: true, render: (v: string | null, c) => <Link to={`/chat?agent=${agentId}&conversation=${c.id}`}>{v || '对话'}</Link> },
        { title: '消息数', dataIndex: 'message_count', width: 90, align: 'right' },
        { title: '摘要', dataIndex: 'summary', ellipsis: true, render: (v: string | null) => (v ? <Tooltip title={v}><span style={{ color: '#6b7280' }}>{v}</span></Tooltip> : <span style={{ color: '#9ca3af' }}>未触发压缩</span>) },
        { title: '最近活跃', dataIndex: 'updated_at', width: 170, render: (v: string) => <TimeCell value={v} /> },
      ]}
    />
  )
}
