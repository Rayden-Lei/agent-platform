import type { AuditLogRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
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

// 审计日志列定义：操作 / 资源用字典标签；资源 ID 能映射到页面的就给链接；摘要一行，详情展开看 JSON。
export function buildAuditColumns(): DataColumn<AuditLogRow>[] {
  return [
    { key: 'id', header: 'ID', width: 80, sortable: true, cell: (r) => <span className="text-muted-foreground">{r.id}</span> },
    { key: 'created_at', header: '时间', width: 170, sortable: true, cell: (r) => <TimeCell value={r.created_at} /> },
    { key: 'username', header: '用户', width: 120, cell: (r) => r.username || <span className="text-muted-foreground">匿名</span> },
    { key: 'action', header: '操作', width: 110, cell: (r) => <StatusTag domain="auditAction" value={r.action} /> },
    { key: 'resource', header: '资源', width: 110, hideOnMobile: true, cell: (r) => <StatusTag domain="auditResource" value={r.resource} /> },
    {
      key: 'resource_id', header: '资源 ID', width: 110, hideOnMobile: true,
      cell: (r) => {
        if (r.resource_id === null || r.resource_id === undefined) return '-'
        const type = AUDIT_RESOURCE_TYPE[r.resource]
        return type ? <ResourceLink type={type} id={r.resource_id} name={`#${r.resource_id}`} /> : `#${r.resource_id}`
      },
    },
    { key: 'summary', header: '摘要', hideOnMobile: true, cell: (r) => <span className="block max-w-[320px] truncate text-muted-foreground">{auditSummary(r.detail)}</span> },
    { key: 'ip', header: 'IP', width: 130, hideOnMobile: true, cell: (r) => r.ip || '-' },
  ]
}
