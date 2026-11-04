import { FolderOpen } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { KnowledgeBaseRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { statusLabel } from '../../constants/status'
import { formatNumber } from '../../utils/format'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

interface Options {
  onEdit: (kb: KnowledgeBaseRow) => void
  onDelete: (kb: KnowledgeBaseRow) => void
}

// 知识库列表列定义（DataTable）：名称进详情页；文档列显示就绪 / 失败 / 处理中的拆分；切片与 token 总量来自列表接口。
export function buildKbColumns({ onEdit, onDelete }: Options): DataColumn<KnowledgeBaseRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', primary: true, sortable: true, width: 220,
      cell: (r) => (
        <Link to={`/knowledge-bases/${r.id}`} onClick={(e) => e.stopPropagation()} className="truncate font-medium hover:underline" style={{ color: 'var(--fg)' }}>
          {r.name}
        </Link>
      ),
    },
    { key: 'description', header: '描述', hideOnMobile: true, cell: (r) => r.description || <span style={{ color: 'var(--fg-subtle)' }}>-</span> },
    {
      key: 'is_public', header: '权限', width: 160, hideOnMobile: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1 flex-wrap">
          <StatusTag domain="visibility" value={r.is_public} />
          {!r.is_public && (r.visible_roles || []).map((role) => <Badge key={role} tone="neutral">{statusLabel('role', role)}</Badge>)}
        </span>
      ),
    },
    {
      key: 'documents', header: '文档', width: 170,
      cell: (r) => (
        <span className="inline-flex items-center gap-1">
          <span>{r.document_count}</span>
          {r.failed_count > 0 && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span><Badge tone="danger">失败 {r.failed_count}</Badge></span>
              </TooltipTrigger>
              <TooltipContent>解析失败的文档，进详情页看原因并重新解析</TooltipContent>
            </Tooltip>
          )}
          {r.processing_count > 0 && <Badge tone="info">处理中 {r.processing_count}</Badge>}
        </span>
      ),
    },
    { key: 'chunks', header: '切片 / Token', width: 140, align: 'right', hideOnMobile: true, cell: (r) => `${formatNumber(r.chunk_count)} / ${formatNumber(r.token_count)}` },
    { key: 'chunk', header: '切片参数', width: 110, hideOnMobile: true, cell: (r) => `${r.chunk_size} / ${r.chunk_overlap}` },
    { key: 'embedding_model', header: '向量模型', width: 160, hideOnMobile: true, cell: (r) => <span className="truncate">{r.embedding_model}</span> },
    { key: 'created_by_username', header: '创建人', width: 100, hideOnMobile: true, cell: (r) => r.created_by_username || <span style={{ color: 'var(--fg-subtle)' }}>-</span> },
    { key: 'updated_at', header: '更新时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 210, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Link to={`/knowledge-bases/${r.id}`}>
            <Button size="sm" variant="ghost" icon={<FolderOpen />}>文档</Button>
          </Link>
          <Button size="sm" variant="secondary" onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除？文档与切片会一并删除" onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger">删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
