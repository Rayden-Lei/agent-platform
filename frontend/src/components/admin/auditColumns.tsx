import type { ColumnsType } from 'antd/es/table'
import type { AuditLogRow } from '../../api'
import { AUDIT_RESOURCE_TYPE } from '../../constants/resources'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'

// 审计详情的一行摘要：取前几个键值拼成 "k=v · k=v"，完整 JSON 在展开行里看
export function auditSummary(detail: Record<string, unknown> | null | undefined, max = 4): string {
  if (!detail || typeof detail !== 'object') return '-'
  const entries = Object.entries(detail)
  if (!entries.length) return '-'
  const parts = entries.slice(0, max).map(([k, v]) => {
    const text = typeof v === 'string' ? v : JSON.stringify(v)
    return `${k}=${text && text.length > 40 ? text.slice(0, 40) + '…' : text}`
  })
  return parts.join(' · ') + (entries.length > max ? ` · 还有 ${entries.length - max} 项` : '')
}

interface Options { sortProps: (field: string) => { sorter: true; sortOrder: 'ascend' | 'descend' | null } }

// 审计日志列定义：操作 / 资源用字典标签；资源 ID 能映射到页面的就给链接；摘要一行，详情展开看 JSON。
export function buildAuditColumns({ sortProps }: Options): ColumnsType<AuditLogRow> {
  return [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 80, ...sortProps('id') },
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 170, ...sortProps('created_at'), render: (v: string | null) => <TimeCell value={v} /> },
    { title: '用户', dataIndex: 'username', width: 120, render: (v: string) => v || <span style={{ color: '#9ca3af' }}>匿名</span> },
    { title: '操作', dataIndex: 'action', width: 110, render: (v: string) => <StatusTag domain="auditAction" value={v} /> },
    { title: '资源', dataIndex: 'resource', width: 110, render: (v: string) => <StatusTag domain="auditResource" value={v} /> },
    {
      title: '资源 ID', dataIndex: 'resource_id', width: 110,
      render: (v: number | null, r) => {
        if (v === null || v === undefined) return '-'
        const type = AUDIT_RESOURCE_TYPE[r.resource]
        return type ? <ResourceLink type={type} id={v} name={`#${v}`} /> : `#${v}`
      },
    },
    { title: '摘要', dataIndex: 'detail', ellipsis: true, render: (v: Record<string, unknown>) => auditSummary(v) },
    { title: 'IP', dataIndex: 'ip', width: 130, render: (v: string | null) => v || '-' },
  ]
}
