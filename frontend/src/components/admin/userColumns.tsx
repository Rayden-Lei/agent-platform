import type { UserRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

interface Options {
  meId?: number
  onOpen: (u: UserRow) => void
  onToggle: (u: UserRow) => Promise<unknown>
  onEdit: (u: UserRow) => void
  onResetPassword: (u: UserRow) => void
  onDelete: (u: UserRow) => void
}

// 用户列表列定义：状态列为启停开关；对自己的账号禁止停用 / 删除（服务端同样拒绝，这里只是不给误操作入口）。
export function buildUserColumns({ meId, onOpen, onToggle, onEdit, onResetPassword, onDelete }: Options): DataColumn<UserRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'username', header: '用户名', sortable: true, primary: true, width: 200,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5 min-w-0">
          <button type="button" onClick={(e) => { e.stopPropagation(); onOpen(r) }} className="hover:underline truncate" style={{ color: 'var(--fg)', fontWeight: 550 }}>
            {r.username}
          </button>
          {r.id === meId && <span className="text-[12px]" style={{ color: 'var(--fg-subtle)' }}>（我）</span>}
          {/* 重置密码或首次登录后还没改密：该账号除改密外调任何接口都 403（docs/15 OP-04） */}
          {r.must_change_password && <Badge tone="warning" title="下次登录必须先修改密码">待改密</Badge>}
        </span>
      ),
    },
    { key: 'role', header: '角色', width: 100, sortable: true, cell: (r) => <StatusTag domain="role" value={r.role} /> },
    {
      key: 'status', header: '状态', width: 80,
      cell: (r) => (r.id === meId
        ? <span title="不能停用自己"><EnableSwitch checked={r.is_active} disabled onToggle={() => Promise.resolve()} /></span>
        : <EnableSwitch checked={r.is_active} onToggle={() => onToggle(r)} />),
    },
    { key: 'created_at', header: '创建时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.created_at} /> },
    { key: 'updated_at', header: '更新时间', width: 168, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 230, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>改角色</Button>
          <Button size="sm" variant="secondary" onClick={() => onResetPassword(r)}>重置密码</Button>
          <InlineConfirm message="确定删除该用户？其创建的资源保留但创建人置空" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger" disabled={r.id === meId}>删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
