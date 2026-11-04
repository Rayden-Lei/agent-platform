import { Link } from 'react-router-dom'
import type { PromptTemplateRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import TimeCell from '../common/TimeCell'

interface Options {
  onOpen: (t: PromptTemplateRow) => void
  onEdit: (t: PromptTemplateRow) => void
  onDelete: (t: PromptTemplateRow) => void
}

// 模板列表列定义：名称打开抽屉；变量列标出必填；智能体数可跳到按模板筛选的智能体列表。
export function buildTemplateColumns({ onOpen, onEdit, onDelete }: Options): DataColumn<PromptTemplateRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', sortable: true, primary: true, width: 190,
      cell: (r) => (
        <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r) }} className="hover:underline text-left truncate" style={{ color: 'var(--fg)', fontWeight: 550 }}>
          {r.name}
        </button>
      ),
    },
    { key: 'description', header: '描述', width: 240, hideOnMobile: true, cell: (r) => (r.description ? <span className="block truncate" style={{ color: 'var(--fg-muted)' }}>{r.description}</span> : <span style={{ color: 'var(--fg-subtle)' }}>-</span>) },
    {
      key: 'variables', header: '变量', width: 250, hideOnMobile: true,
      cell: (r) => (r.variables.length
        ? (
          <span className="inline-flex items-center gap-1 flex-wrap">
            {r.variables.map((v) => <Badge key={v.name} tone="neutral">{v.name}{v.required ? ' *' : ''}</Badge>)}
          </span>
        )
        : <span style={{ color: 'var(--fg-subtle)' }}>无</span>),
    },
    { key: 'version', header: '版本', width: 76, sortable: true, hideOnMobile: true, cell: (r) => `v${r.version}` },
    {
      key: 'agents_count', header: '智能体', width: 80, align: 'right', hideOnMobile: true,
      cell: (r) => (r.agents_count
        ? <Link to={`/agents?prompt_template_id=${r.id}`} onClick={(e) => e.stopPropagation()} style={{ color: 'var(--accent)' }}>{r.agents_count}</Link>
        : <span style={{ color: 'var(--fg-subtle)' }}>0</span>),
    },
    { key: 'created_by_username', header: '创建人', width: 96, hideOnMobile: true, cell: (r) => r.created_by_username || <span style={{ color: 'var(--fg-subtle)' }}>-</span> },
    { key: 'updated_at', header: '更新时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 150, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>编辑</Button>
          {/* 仍被智能体绑定时后端 409，提示里带绑定数 */}
          <InlineConfirm message="确定删除？仍被智能体绑定时会被拒绝" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
