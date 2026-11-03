import { HistoryOutlined, MessageOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import type { AgentRow } from '../../api'
import type { DataColumn, SortState } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

// 智能体列表列定义（新版 DataTable）：名称进详情页；模型 / 模板可跳转；工具与知识库显示绑定数；
// 近 7 天运行数（不计调试）与最近运行时间来自列表接口。配置列是草稿，状态旁标"未发布修改"。
// 排序走服务端：sortable 的列点表头触发 onSortChange。
interface Options {
  sort: SortState
  onChat: (a: AgentRow) => void
  onPublish: (a: AgentRow) => void
  onEdit: (a: AgentRow) => void
  onDelete: (a: AgentRow) => void
}

export function buildAgentColumns({ onChat, onPublish, onEdit, onDelete }: Options): DataColumn<AgentRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', sortable: true, primary: true, width: 220,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <Link to={`/agents/${r.id}`} onClick={(e) => e.stopPropagation()} className="hover:underline truncate" style={{ color: 'var(--fg)', fontWeight: 550 }}>
            {r.name}
          </Link>
          {/* 模板改版不自动传播：提示开发者重新保存以按最新版本渲染 */}
          {r.prompt_template_outdated && (
            <Badge tone="warning" title="绑定的提示词模板已有新版本，重新保存即按最新版本渲染">模板有新版本</Badge>
          )}
        </span>
      ),
    },
    {
      key: 'status', header: '状态', width: 150, sortable: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5 flex-wrap">
          <StatusTag domain="agent" value={r.status} />
          {/* 保存只改草稿，发布后才对外生效（docs/15 FR-039） */}
          {r.has_unpublished_changes && <Badge tone="warning" title="草稿与线上版本不同，发布后对外生效">未发布修改</Badge>}
        </span>
      ),
    },
    {
      key: 'model_name', header: '模型', width: 150, hideOnMobile: true,
      cell: (r) => <ResourceLink type="model" id={r.model_id} name={r.model_name} />,
    },
    {
      key: 'bindings', header: '能力', width: 210, hideOnMobile: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1 flex-wrap">
          <Badge tone="neutral" title="绑定的工具数">工具 {r.tool_ids?.length ?? 0}</Badge>
          <Badge tone="neutral" title="绑定的知识库数">知识库 {r.kb_ids?.length ?? 0}</Badge>
          {r.prompt_template_id && <ResourceLink type="template" id={r.prompt_template_id} name={r.prompt_template_name ? `模板：${r.prompt_template_name}` : '模板'} />}
        </span>
      ),
    },
    {
      key: 'runs_7d', header: '近 7 天运行', width: 104, align: 'right', hideOnMobile: true,
      cell: (r) => (r.runs_7d ? <Link to={`/runs?agent_id=${r.id}`} onClick={(e) => e.stopPropagation()} style={{ color: 'var(--accent)' }}>{r.runs_7d}</Link> : <span style={{ color: 'var(--fg-subtle)' }}>0</span>),
    },
    {
      key: 'last_run_at', header: '最近运行', width: 104, hideOnMobile: true,
      cell: (r) => <TimeCell value={r.last_run_at} mode="relative" />,
    },
    {
      key: 'version', header: '线上版本', width: 88, sortable: true, hideOnMobile: true,
      cell: (r) => (r.published_version ? `v${r.published_version}` : <span style={{ color: 'var(--fg-subtle)' }}>-</span>),
    },
    {
      key: 'created_by_username', header: '创建人', width: 96, hideOnMobile: true,
      cell: (r) => r.created_by_username || <span style={{ color: 'var(--fg-subtle)' }}>-</span>,
    },
    {
      key: 'updated_at', header: '更新时间', width: 168, sortable: true,
      cell: (r) => <TimeCell value={r.updated_at} />,
    },
    {
      key: 'actions', header: '操作', width: 250, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="ghost" icon={<MessageOutlined />} disabled={r.status !== 'published'} onClick={() => onChat(r)}>对话</Button>
          {(r.status !== 'published' || r.has_unpublished_changes) && (
            <Button size="sm" variant="primary" onClick={() => onPublish(r)}>
              {r.status === 'offline' && !r.has_unpublished_changes ? '重新上线' : '发布'}
            </Button>
          )}
          <Button size="sm" variant="secondary" icon={<HistoryOutlined />} onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除？会话、消息与运行记录会一并删除" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
