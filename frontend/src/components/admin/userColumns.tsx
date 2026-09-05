import { Button, Popconfirm, Space, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { UserRow } from '../../api'
import EnableSwitch from '../common/EnableSwitch'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  meId?: number
  onOpen: (u: UserRow) => void
  onToggle: (u: UserRow) => Promise<unknown>
  onEdit: (u: UserRow) => void
  onResetPassword: (u: UserRow) => void
  onDelete: (u: UserRow) => void
}

// 用户列表列定义：状态列为启停开关；对自己的账号禁止停用 / 删除（服务端同样拒绝，这里只是不给误操作入口）。
export function buildUserColumns({ sortProps, meId, onOpen, onToggle, onEdit, onResetPassword, onDelete }: Options): ColumnsType<UserRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '用户名', dataIndex: 'username', key: 'username', ...sortProps('username'), render: (v: string, r) => <a onClick={() => onOpen(r)}>{v}{r.id === meId && <span style={{ color: '#9ca3af', fontSize: 12 }}>（我）</span>}</a> },
    { title: '角色', dataIndex: 'role', key: 'role', width: 100, ...sortProps('role'), render: (v: string) => <StatusTag domain="role" value={v} /> },
    {
      title: '状态', key: 'status', width: 80,
      render: (_, r) => (r.id === meId ? <Tooltip title="不能停用自己"><span><EnableSwitch checked={r.is_active} disabled onToggle={() => Promise.resolve()} /></span></Tooltip> : <EnableSwitch checked={r.is_active} onToggle={() => onToggle(r)} />),
    },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, ...sortProps('created_at'), render: (v: string | null) => <TimeCell value={v} /> },
    { title: '更新时间', dataIndex: 'updated_at', width: 170, render: (v: string | null) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 230, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" onClick={() => onEdit(r)}>改角色</Button>
          <Button size="small" onClick={() => onResetPassword(r)}>重置密码</Button>
          <Popconfirm title="确定删除该用户？其创建的资源保留但创建人置空" onConfirm={() => onDelete(r)} disabled={r.id === meId}><Button size="small" danger disabled={r.id === meId}>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
