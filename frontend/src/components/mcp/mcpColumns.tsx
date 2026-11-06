import type { McpServerRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import TimeCell from '../common/TimeCell'

interface Options {
  onOpen: (server: McpServerRow) => void
  onToggle: (server: McpServerRow) => Promise<unknown>
  onSync: (server: McpServerRow) => void
  onEdit: (server: McpServerRow) => void
  onDelete: (server: McpServerRow) => void
  /** 正在同步的服务器 id：同步要连远端，慢的时候按钮要能看出在跑 */
  syncingId: number | null
}

// MCP 服务器列表列定义。
// 三件事必须在列表上看得见：同步过几个工具、上次同步是否失败、服务器本身是否停用。
// last_error 用整行 tooltip 承载完整文案，单元格只放一个"同步失败"徽章 —— 外部报错常常几百字，铺开会把行撑高。
export function buildMcpColumns({ onOpen, onToggle, onSync, onEdit, onDelete, syncingId }: Options): DataColumn<McpServerRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', sortable: true, primary: true, width: 180,
      cell: (r) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onOpen(r) }}
          className="relative after:absolute after:-inset-y-1.5 after:content-[''] hover:underline text-left truncate max-w-full"
          style={{ color: 'var(--fg)', fontWeight: 550 }}
          title={r.name}
        >
          {r.name}
        </button>
      ),
    },
    {
      key: 'url', header: '地址', width: 240, hideOnMobile: true,
      cell: (r) => (
        <span
          className="block truncate"
          title={r.url}
          style={{ color: 'var(--fg-muted)', fontFamily: '"SF Mono",Consolas,monospace', fontSize: 11.5 }}
        >
          {r.url}
        </span>
      ),
    },
    {
      key: 'transport', header: '传输', width: 76, hideOnMobile: true,
      cell: (r) => <Badge tone="neutral">{r.transport === 'sse' ? 'SSE' : 'HTTP'}</Badge>,
    },
    {
      key: 'tools_count', header: '工具', width: 76, align: 'right',
      // 0 个工具时提示"还没同步过"，否则会以为是坏了
      cell: (r) => (r.tools_count
        ? <span title={`已同步 ${r.tools_count} 个远端工具`}>{r.tools_count}</span>
        : <span style={{ color: 'var(--fg-subtle)' }} title="还没有同步过，点操作里的「同步」">0</span>),
    },
    {
      key: 'last_synced_at', header: '上次同步', width: 168, hideOnMobile: true,
      cell: (r) => (r.last_error
        ? <span title={r.last_error}><Badge tone="danger">同步失败</Badge></span>
        : r.last_synced_at ? <TimeCell value={r.last_synced_at} /> : <span style={{ color: 'var(--fg-subtle)' }}>从未同步</span>),
    },
    { key: 'is_enabled', header: '启用', width: 76, cell: (r) => <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} /> },
    {
      key: 'actions', header: '操作', width: 200, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" disabled={!r.is_enabled || syncingId === r.id} onClick={() => onSync(r)}>
            {syncingId === r.id ? '同步中…' : '同步'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>编辑</Button>
          {/* 删除服务器不删工具：工具保留但全部停用，避免破坏智能体的 tool_ids 引用 */}
          <InlineConfirm message="删除服务器？它同步出的工具会保留但全部停用" danger onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
