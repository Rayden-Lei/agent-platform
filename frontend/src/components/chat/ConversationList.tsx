import { Button, List, Popconfirm, Tooltip, Typography, message } from 'antd'
import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import type { ConversationRow } from '../../api'
import { deleteConversation } from '../../api'
import EmptyState from '../common/EmptyState'
import SearchInput from '../common/SearchInput'
import { errorText } from '../../utils/errors'
import { fromNow } from '../../utils/time'

// 会话侧栏：按当前智能体过滤的会话列表，标题搜索、相对时间、消息数、摘要提示、加载更多、删除。
interface Props {
  conversations: ConversationRow[]
  total: number
  currentId: number | null
  q?: string
  onSearch: (q?: string) => void
  onSelect: (id: number) => void
  onNew: () => void
  onLoadMore: () => void
  onDeleted: (id: number) => void
  agentSelector: React.ReactNode
  loading?: boolean
}

export default function ConversationList({ conversations, total, currentId, q, onSearch, onSelect, onNew, onLoadMore, onDeleted, agentSelector, loading }: Props) {
  const remove = async (id: number) => {
    try { await deleteConversation(id); onDeleted(id) } catch (e) { message.error(errorText(e, '删除会话失败')) }
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, height: '100%', minHeight: 0 }}>
      {agentSelector}
      <Button type="primary" icon={<PlusOutlined />} block onClick={onNew}>新对话</Button>
      <SearchInput value={q} onChange={onSearch} placeholder="搜索会话标题" width={196} />
      <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
        {conversations.length === 0 && !loading ? (
          <EmptyState description={q ? '没有匹配的会话' : '该智能体下还没有会话，发送第一条消息即可创建'} />
        ) : (
          <List
            size="small"
            loading={loading && conversations.length === 0}
            dataSource={conversations}
            renderItem={(c) => (
              <List.Item
                onClick={() => onSelect(c.id)}
                style={{ cursor: 'pointer', background: currentId === c.id ? '#e8eefb' : 'transparent', padding: '6px 8px', borderRadius: 6, alignItems: 'flex-start' }}
                actions={[
                  <Popconfirm key="d" title="删除会话？" onConfirm={(e) => { e?.stopPropagation(); remove(c.id) }} onCancel={(e) => e?.stopPropagation()}>
                    <DeleteOutlined onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}
              >
                <Tooltip title={c.summary ? `摘要：${c.summary}` : undefined} placement="right">
                  <div style={{ minWidth: 0 }}>
                    <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>{c.title || '对话'}</div>
                    <Typography.Text type="secondary" style={{ fontSize: 11 }}>{fromNow(c.updated_at)} · {c.message_count} 条{c.summary ? ' · 已压缩' : ''}</Typography.Text>
                  </div>
                </Tooltip>
              </List.Item>
            )}
          />
        )}
        {conversations.length < total && <Button size="small" type="link" block onClick={onLoadMore}>加载更多（{conversations.length}/{total}）</Button>}
      </div>
    </div>
  )
}
