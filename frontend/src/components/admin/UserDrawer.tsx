import { useMemo } from 'react'
import { Button, Descriptions, Drawer, Space, Table, Typography } from 'antd'
import { listAuditLogs, type AuditLogRow, type UserRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import EmptyState from '../common/EmptyState'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { auditSummary } from './auditColumns'

// 用户详情抽屉：账号信息 + 该用户最近的审计记录（按用户名过滤审计日志）。
interface Props { user: UserRow | null; onClose: () => void; onEdit: (u: UserRow) => void; onResetPassword: (u: UserRow) => void }

export default function UserDrawer({ user, onClose, onEdit, onResetPassword }: Props) {
  const filters = useMemo(() => ({ username: user?.username }), [user?.username])
  const logs = usePagedList<AuditLogRow>(listAuditLogs, { filters, pageSize: 10, auto: !!user, emptyText: <EmptyState description="该用户还没有操作记录" /> })
  return (
    <Drawer title={user ? `用户：${user.username}` : ''} open={!!user} onClose={onClose} width={720} destroyOnHidden
      extra={user && <Space><Button onClick={() => onResetPassword(user)}>重置密码</Button><Button type="primary" onClick={() => onEdit(user)}>改角色</Button></Space>}>
      {user && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Descriptions size="small" bordered column={2} items={[
            { key: 'role', label: '角色', children: <StatusTag domain="role" value={user.role} /> },
            { key: 'active', label: '状态', children: <StatusTag domain="enabled" value={user.is_active} /> },
            { key: 'created', label: '创建时间', children: <TimeCell value={user.created_at} /> },
            { key: 'updated', label: '更新时间', children: <TimeCell value={user.updated_at} /> },
          ]} />
          <div>
            <Typography.Text strong>最近操作（审计日志）</Typography.Text>
            <Table size="small" rowKey="id" style={{ marginTop: 8 }} {...logs.tableProps} columns={[
              { title: '时间', dataIndex: 'created_at', width: 160, render: (v: string | null) => <TimeCell value={v} /> },
              { title: '操作', dataIndex: 'action', width: 100, render: (v: string) => <StatusTag domain="auditAction" value={v} /> },
              { title: '资源', dataIndex: 'resource', width: 100, render: (v: string, r) => <span><StatusTag domain="auditResource" value={v} />{r.resource_id !== null && <span style={{ color: '#9ca3af', marginLeft: 4 }}>#{r.resource_id}</span>}</span> },
              { title: '摘要', dataIndex: 'detail', ellipsis: true, render: (v: Record<string, unknown>) => auditSummary(v) },
              { title: 'IP', dataIndex: 'ip', width: 120, render: (v: string | null) => v || '-' },
            ]} />
          </div>
        </div>
      )}
    </Drawer>
  )
}
