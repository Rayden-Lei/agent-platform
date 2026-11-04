import { Link } from 'react-router-dom'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { listConversations, type ConversationRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
import TimeCell from '../common/TimeCell'
import DataTable, { type DataColumn } from '../table/DataTable'

// 智能体详情的会话页签：只列当前登录用户与该智能体的会话（会话按用户行级隔离），可跳到对话页继续。
interface Props { agentId: number }

export default function AgentConversationsTab({ agentId }: Props) {
  const list = usePagedList<ConversationRow>(listConversations, { filters: { agent_id: agentId }, pageSize: 10 })

  const columns: DataColumn<ConversationRow>[] = [
    {
      key: 'title', header: '标题', primary: true,
      cell: (c) => <Link to={`/chat?agent=${agentId}&conversation=${c.id}`} className="text-primary hover:underline">{c.title || '对话'}</Link>,
    },
    {
      key: 'message_count', header: '消息数', width: 90, align: 'right', hideOnMobile: true,
      cell: (c) => <span className="tabular-nums text-[13.5px]">{c.message_count}</span>,
    },
    {
      key: 'summary', header: '摘要',
      // 摘要可能很长：单元格里截断，完整内容放浮层，不在表格里撑开一行
      cell: (c) => (c.summary
        ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="block truncate text-[13.5px] text-muted-foreground">{c.summary}</span>
            </TooltipTrigger>
            <TooltipContent className="max-w-[420px] whitespace-pre-wrap">{c.summary}</TooltipContent>
          </Tooltip>
        )
        : <span className="text-[13.5px] text-muted-foreground">未触发压缩</span>),
    },
    { key: 'updated_at', header: '最近活跃', width: 170, cell: (c) => <TimeCell value={c.updated_at} /> },
  ]

  return (
    <DataTable
      columns={columns}
      rows={list.items}
      rowKey={(c) => c.id}
      loading={list.loading}
      error={list.error}
      empty={<EmptyState description="你还没有与该智能体的会话" />}
      onRetry={list.reload}
      page={list.page}
      pageSize={list.pageSize}
      total={list.total}
      onPageChange={list.load}
    />
  )
}
