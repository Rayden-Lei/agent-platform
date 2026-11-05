import { FlaskConical } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { ToolRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import StatusTag from '../common/StatusTag'

interface Options {
  canManage: boolean
  onOpen: (tool: ToolRow) => void
  onToggle: (tool: ToolRow) => Promise<unknown>
  onTest: (tool: ToolRow) => void
  onEdit: (tool: ToolRow) => void
  onDelete: (tool: ToolRow) => void
}

export const paramCount = (r: ToolRow) => Object.keys(r.config?.parameters?.properties || {}).length

// 工具列表列定义：名称打开抽屉；HTTP 工具显示方法与地址；未声明参数的 HTTP 工具模型只能空参调用，标黄提醒。
export function buildToolColumns({ canManage, onOpen, onToggle, onTest, onEdit, onDelete }: Options): DataColumn<ToolRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', sortable: true, primary: true, width: 170,
      cell: (r) => (
        <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r) }} className="relative after:absolute after:-inset-y-1.5 after:content-[''] hover:underline text-left truncate" style={{ color: 'var(--fg)', fontWeight: 550 }}>
          {r.name}
        </button>
      ),
    },
    {
      key: 'type', header: '类型', width: 168, sortable: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1 flex-wrap">
          <StatusTag domain="toolType" value={r.type} />
          {r.type === 'http' && (paramCount(r) ? <Badge tone="neutral">{paramCount(r)} 个参数</Badge> : <Badge tone="warning">未声明参数</Badge>)}
        </span>
      ),
    },
    { key: 'description', header: '描述', width: 260, hideOnMobile: true, cell: (r) => <span className="block truncate" style={{ color: 'var(--fg-muted)' }}>{r.description}</span> },
    {
      key: 'request', header: '请求', width: 250, hideOnMobile: true,
      cell: (r) => (r.type === 'http'
        ? (
          <span className="inline-flex items-center gap-1.5 min-w-0">
            <Badge tone="info">{(r.config?.method || 'POST').toUpperCase()}</Badge>
            <span className="truncate" style={{ color: 'var(--fg-muted)', fontFamily: '"SF Mono",Consolas,monospace', fontSize: 11.5 }} title={r.config?.url}>{r.config?.url || '-'}</span>
          </span>
        )
        : <span style={{ color: 'var(--fg-subtle)' }}>服务内置实现</span>),
    },
    { key: 'timeout', header: '超时', width: 68, align: 'right', hideOnMobile: true, cell: (r) => `${r.timeout}s` },
    {
      key: 'status', header: '状态', width: 76,
      cell: (r) => <EnableSwitch checked={r.is_enabled} disabled={!canManage} onToggle={() => onToggle(r)} />,
    },
    {
      key: 'agents_count', header: '智能体', width: 80, align: 'right', hideOnMobile: true,
      cell: (r) => (r.agents_count
        ? <Link to={`/agents?tool_id=${r.id}`} onClick={(e) => e.stopPropagation()} style={{ color: 'var(--accent)' }}>{r.agents_count}</Link>
        : <span style={{ color: 'var(--fg-subtle)' }}>0</span>),
    },
    {
      key: 'actions', header: '操作', width: 200, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" icon={<FlaskConical />} onClick={() => onTest(r)}>测试</Button>
          <Button size="sm" variant="secondary" disabled={!canManage} onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除？绑定了该工具的智能体会失去这项能力" danger onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger" disabled={!canManage}>删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
