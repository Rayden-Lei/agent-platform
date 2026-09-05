import { useMemo, useState } from 'react'
import { Button, Select, Table, message } from 'antd'
import { DatabaseOutlined, PlusOutlined } from '@ant-design/icons'
import { batchKBs, deleteKB, listKBs, type KnowledgeBaseRow } from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import { useBatchAction } from '../hooks/useBatchAction'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import BatchActionBar from '../components/common/BatchActionBar'
import BatchResultModal from '../components/common/BatchResultModal'
import EmbeddingAlert from '../components/kb/EmbeddingAlert'
import KbForm from '../components/kb/KbForm'
import { buildKbColumns } from '../components/kb/kbColumns'
import { errorText } from '../utils/errors'

type Filters = { q?: string; is_public?: string }
const DEFAULTS: Filters = { q: undefined, is_public: undefined }

// 知识库列表：筛选 + 排序 + 批量删除；文档 / 切片统计随列表返回；文档管理与检索评测在详情页。
export default function KnowledgeBases() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<KnowledgeBaseRow | null>(null)
  const list = usePagedList<KnowledgeBaseRow>(listKBs, {
    filters,
    selectable: true,
    emptyText: <EmptyState description="还没有知识库。新建后上传 PDF / Word / Markdown / TXT，解析入库即可被智能体检索。" action={{ label: '新建知识库', onClick: () => { setEditing(null); setFormOpen(true) } }} />,
  })
  const batch = useBatchAction(() => { list.clearSelection(); list.reload() })
  const remove = async (kb: KnowledgeBaseRow) => { try { await deleteKB(kb.id); list.reload() } catch (e) { message.error(errorText(e, '删除失败')) } }
  const columns = useMemo(() => buildKbColumns({ sortProps: list.sortProps, onEdit: (kb) => { setEditing(kb); setFormOpen(true) }, onDelete: remove }), [list.sortProps]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ListPage
      header={<PageHeader icon={<DatabaseOutlined />} title="知识库" description="文档解析切片后向量入库；权限决定哪些角色能在检索与对话中引用。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing(null); setFormOpen(true) }}>新建知识库</Button>} />}
      alert={<EmbeddingAlert />}
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索知识库名称" />
          <Select allowClear placeholder="权限" style={{ width: 110 }} value={filters.is_public} onChange={(v) => setFilters({ is_public: v })} options={[{ value: 'true', label: '公开' }, { value: 'false', label: '受限' }]} />
        </FilterBar>
      }
      batch={<BatchActionBar count={list.selectedKeys.length} onClear={list.clearSelection} running={batch.running} actions={[{ key: 'delete', label: '批量删除', danger: true, confirm: `删除选中的 ${list.selectedKeys.length} 个知识库？文档与切片会一并删除`, run: () => batch.run(() => batchKBs(list.selectedKeys), '已删除') }]} />}
    >
      <Table rowKey="id" {...list.tableProps} columns={columns} scroll={{ x: 'max-content' }} />
      <KbForm open={formOpen} editing={editing} onClose={() => setFormOpen(false)} onSaved={list.reload} />
      <BatchResultModal result={batch.result} onClose={batch.closeResult} nameOf={(id) => list.items.find((k) => k.id === id)?.name} />
    </ListPage>
  )
}
