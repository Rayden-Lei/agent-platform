import { Button, Popconfirm, Progress, Space, Tag, Tooltip } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ApiKeyRow } from '../../api'
import EnableSwitch from '../common/EnableSwitch'
import TimeCell from '../common/TimeCell'

interface Options {
  sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null }
  isAdmin: boolean
  onOpen: (k: ApiKeyRow) => void
  onToggle: (k: ApiKeyRow) => Promise<unknown>
  onEdit: (k: ApiKeyRow) => void
  onDelete: (k: ApiKeyRow) => void
}

// 配额进度：用量占比 ≥ 90% 标红提醒续配额
export function QuotaCell({ used, quota }: { used: number; quota: number }) {
  if (!quota) return <span>{used} / 不限</span>
  const ratio = Math.min(used / quota, 1)
  return (
    <Tooltip title={`已用 ${used} / 配额 ${quota}`}>
      <div style={{ minWidth: 120 }}>
        <Progress percent={Math.round(ratio * 100)} size="small" status={ratio >= 1 ? 'exception' : ratio >= 0.9 ? 'active' : 'normal'} strokeColor={ratio >= 0.9 ? '#dc2626' : undefined} format={() => `${used}/${quota}`} />
      </div>
    </Tooltip>
  )
}

// API Key 列表列定义：Key 只显示前缀；配额用进度条；admin 视角多一列归属。
export function buildApiKeyColumns({ sortProps, isAdmin, onOpen, onToggle, onEdit, onDelete }: Options): ColumnsType<ApiKeyRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, ...sortProps('id') },
    { title: '名称', dataIndex: 'name', key: 'name', ...sortProps('name'), ellipsis: true, render: (v: string, r) => <a onClick={() => onOpen(r)}>{v}</a> },
    { title: 'Key 前缀', dataIndex: 'key_prefix', width: 130, render: (v: string) => <span style={{ fontFamily: 'monospace' }}>{v}…</span> },
    ...(isAdmin ? [{ title: '归属', dataIndex: 'username', width: 110, render: (v: string | null) => v || '-' } as ColumnsType<ApiKeyRow>[number]] : []),
    { title: '配额 / 已用', key: 'quota', width: 170, render: (_, r) => <QuotaCell used={r.used} quota={r.quota} /> },
    {
      title: '来源限制', dataIndex: 'allowed_ips', width: 110,
      render: (v: string[]) => (v.length === 0 ? <span style={{ color: '#9ca3af' }}>不限制</span> : <Tooltip title={<div style={{ fontFamily: 'monospace', whiteSpace: 'pre-line' }}>{v.join('\n')}</div>}><Tag>{v.length} 条</Tag></Tooltip>),
    },
    { title: '限速 / 分钟', dataIndex: 'rate_limit_per_minute', width: 100, align: 'right', render: (v: number) => (v === 0 ? <span style={{ color: '#9ca3af' }}>默认</span> : v) },
    { title: '状态', key: 'status', width: 80, render: (_, r) => <EnableSwitch checked={r.is_enabled} onToggle={() => onToggle(r)} /> },
    { title: '最后使用', dataIndex: 'last_used_at', key: 'last_used_at', width: 120, ...sortProps('last_used_at'), render: (v: string | null) => <TimeCell value={v} mode="relative" /> },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170, ...sortProps('created_at'), render: (v: string | null) => <TimeCell value={v} /> },
    {
      title: '操作', key: 'actions', width: 140, fixed: 'right',
      render: (_, r) => (
        <Space size={4}>
          <Button size="small" onClick={() => onEdit(r)}>编辑</Button>
          <Popconfirm title="确定删除？使用该 Key 的调用会立即失效" onConfirm={() => onDelete(r)}><Button size="small" danger>删除</Button></Popconfirm>
        </Space>
      ),
    },
  ]
}
