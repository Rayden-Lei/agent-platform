import { useMemo } from 'react'
import { Table } from 'antd'
import { AuditOutlined } from '@ant-design/icons'
import { listAuditLogs, type AuditLogRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import EmptyState from '../components/common/EmptyState'
import JsonView from '../components/common/JsonView'
import AuditFilters, { type AuditFilterValues } from '../components/admin/AuditFilters'
import { auditSummary, buildAuditColumns } from '../components/admin/auditColumns'
import { exportCsv } from '../utils/csv'
import { formatDateTime } from '../utils/time'
import { statusLabel } from '../constants/status'

const DEFAULTS: AuditFilterValues = { username: undefined, action: undefined, resource: undefined, resource_id: undefined, ip: undefined, created_from: undefined, created_to: undefined }

// 审计日志（只读）：多条件筛选同步 URL、服务端排序、展开看完整 detail、导出当前页 CSV。
export default function AuditLogs() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const list = usePagedList<AuditLogRow>(listAuditLogs, { filters, defaultSort: { field: 'id', order: 'desc' }, emptyText: <EmptyState description="没有匹配的审计记录；登录、增删改、发布 / 回滚、检索都会留痕" /> })
  const columns = useMemo(() => buildAuditColumns({ sortProps: list.sortProps }), [list.sortProps])
  const exportPage = () => exportCsv('审计日志', [
    { title: 'ID', value: (r) => r.id },
    { title: '时间', value: (r) => formatDateTime(r.created_at) },
    { title: '用户', value: (r) => r.username },
    { title: '操作', value: (r) => statusLabel('auditAction', r.action) },
    { title: '资源', value: (r) => statusLabel('auditResource', r.resource) },
    { title: '资源 ID', value: (r) => r.resource_id },
    { title: '详情', value: (r) => JSON.stringify(r.detail) },
    { title: 'IP', value: (r) => r.ip },
  ], list.items)

  return (
    <ListPage
      header={<PageHeader icon={<AuditOutlined />} title="审计日志" description="谁在什么时候对哪条数据做了什么；只读，不可删改。导出只含当前页。" />}
      filters={<AuditFilters values={filters} onChange={setFilters} onReset={resetFilters} onRefresh={list.reload} onExport={exportPage} loading={list.loading} />}
    >
      <Table
        rowKey="id"
        {...list.tableProps}
        columns={columns}
        scroll={{ x: 'max-content' }}
        expandable={{
          rowExpandable: (r) => !!r.detail && Object.keys(r.detail).length > 0,
          expandedRowRender: (r) => <JsonView title={auditSummary(r.detail, 2)} value={r.detail} maxHeight={320} />,
        }}
      />
    </ListPage>
  )
}
