import { useMemo, type ReactNode } from 'react'
import { KeyRound, UserCog } from 'lucide-react'
import { listAuditLogs, type AuditLogRow, type UserRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import DataTable, { type DataColumn } from '../table/DataTable'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { auditSummary } from './auditColumns'

// 用户详情抽屉：账号信息 + 该用户最近的审计记录（按用户名过滤审计日志）。
interface Props { user: UserRow | null; onClose: () => void; onEdit: (u: UserRow) => void; onResetPassword: (u: UserRow) => void }

// 详情字段：标签在上、值在下（替代 antd Descriptions 的表格块，窄屏也不会挤成一团）
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      <dd className="m-0 mt-1 text-[13px] text-foreground">{children}</dd>
    </div>
  )
}

export default function UserDrawer({ user, onClose, onEdit, onResetPassword }: Props) {
  const filters = useMemo(() => ({ username: user?.username }), [user?.username])
  const logs = usePagedList<AuditLogRow>(listAuditLogs, { filters, pageSize: 10, auto: !!user })
  const columns = useMemo<DataColumn<AuditLogRow>[]>(() => [
    { key: 'created_at', header: '时间', width: 150, cell: (r) => <TimeCell value={r.created_at} /> },
    { key: 'action', header: '操作', width: 90, cell: (r) => <StatusTag domain="auditAction" value={r.action} /> },
    {
      key: 'resource', header: '资源', width: 100,
      cell: (r) => (
        <span className="inline-flex items-center gap-1">
          <StatusTag domain="auditResource" value={r.resource} />
          {r.resource_id !== null && <span className="text-[12px] text-muted-foreground">#{r.resource_id}</span>}
        </span>
      ),
    },
    { key: 'detail', header: '摘要', cell: (r) => <span className="truncate">{auditSummary(r.detail)}</span> },
    { key: 'ip', header: 'IP', width: 110, cell: (r) => (r.ip ? <span className="font-mono text-[12px]">{r.ip}</span> : <span className="text-muted-foreground">-</span>) },
  ], [])

  return (
    <Drawer
      open={!!user}
      width={720}
      title={user ? `用户：${user.username}` : ''}
      onClose={onClose}
      extra={user && (
        <>
          <Button icon={<KeyRound className="size-3.5" />} onClick={() => onResetPassword(user)}>重置密码</Button>
          <Button variant="primary" icon={<UserCog className="size-3.5" />} onClick={() => onEdit(user)}>改角色</Button>
        </>
      )}
    >
      {user && (
        <div className="flex flex-col gap-4">
          <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-3 rounded-lg border border-border bg-card p-3.5">
            <Field label="角色"><StatusTag domain="role" value={user.role} /></Field>
            <Field label="状态"><StatusTag domain="enabled" value={user.is_active} /></Field>
            <Field label="创建时间"><TimeCell value={user.created_at} /></Field>
            <Field label="更新时间"><TimeCell value={user.updated_at} /></Field>
          </dl>

          <div className="flex flex-col gap-2">
            <h3 className="m-0 text-[13px] font-semibold text-foreground">最近操作（审计日志）</h3>
            <DataTable
              columns={columns}
              rows={logs.items}
              rowKey={(r) => r.id}
              loading={logs.loading}
              error={logs.error}
              empty={<EmptyState description="该用户还没有操作记录" />}
              onRetry={logs.reload}
              page={logs.page}
              pageSize={logs.pageSize}
              total={logs.total}
              onPageChange={logs.load}
            />
          </div>
        </div>
      )}
    </Drawer>
  )
}
