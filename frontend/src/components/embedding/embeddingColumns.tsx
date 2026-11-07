import type { EmbeddingModelRow } from '../../api'
import type { DataColumn } from '../table/DataTable'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import EnableSwitch from '../common/EnableSwitch'
import TimeCell from '../common/TimeCell'

interface Options {
  onOpen: (model: EmbeddingModelRow) => void
  onToggle: (model: EmbeddingModelRow) => Promise<unknown>
  onTest: (model: EmbeddingModelRow) => void
  onEdit: (model: EmbeddingModelRow) => void
  onDelete: (model: EmbeddingModelRow) => void
  /** 正在测试的模型 id：连通测试要真的发一次请求，慢的时候按钮要能看出在跑 */
  testingId: number | null
  canManage: boolean
  /** 切片表的向量列宽：维度与它不一致的模型存不进去，列表要能一眼看出来 */
  requiredDim: number
}

// 向量模型列表列定义。
// 三件事必须在列表上看得见：维度是否与切片表一致、被几个知识库绑着（绑着就不能删/停）、连通是否测过。
export function buildEmbeddingColumns({ onOpen, onToggle, onTest, onEdit, onDelete, testingId, canManage, requiredDim }: Options): DataColumn<EmbeddingModelRow>[] {
  return [
    { key: 'id', header: 'ID', width: 64, sortable: true, cell: (r) => <span style={{ color: 'var(--fg-muted)' }}>{r.id}</span> },
    {
      key: 'name', header: '名称', sortable: true, primary: true, width: 200,
      cell: (r) => (
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); onOpen(r) }}
          className="relative after:absolute after:-inset-y-1.5 after:content-[''] hover:underline text-left truncate max-w-full"
          style={{ color: 'var(--fg)', fontWeight: 550 }}
          title={r.name}
        >
          {r.name}
        </button>
      ),
    },
    {
      key: 'model_name', header: '模型名', width: 220, hideOnMobile: true,
      cell: (r) => (
        <span className="block truncate" title={r.model_name} style={{ color: 'var(--fg-muted)', fontFamily: '"SF Mono",Consolas,monospace', fontSize: 11.5 }}>
          {r.model_name}
        </span>
      ),
    },
    {
      key: 'dim', header: '维度', width: 90, align: 'right',
      // 与切片表列宽不一致时插入会直接报错，必须在列表上标出来而不是等入库失败才发现
      cell: (r) => (r.dim === requiredDim
        ? <span style={{ fontVariantNumeric: 'tabular-nums' }}>{r.dim}</span>
        : <span title={`切片表向量列宽是 ${requiredDim} 维，维度不一致将无法入库`}><Badge tone="danger">{r.dim} 维 不匹配</Badge></span>),
    },
    {
      key: 'kbs_count', header: '知识库', width: 88, align: 'right',
      // 被绑定的模型不能停用/删除（会让那些库无法入库与检索）
      cell: (r) => (r.kbs_count
        ? <span title={`${r.kbs_count} 个知识库绑定了它，因此不能停用或删除`}>{r.kbs_count}</span>
        : <span style={{ color: 'var(--fg-subtle)' }}>0</span>),
    },
    {
      key: 'api_base', header: '地址', width: 240, hideOnMobile: true,
      cell: (r) => (
        <span className="block truncate" title={r.api_base} style={{ color: 'var(--fg-muted)', fontFamily: '"SF Mono",Consolas,monospace', fontSize: 11.5 }}>
          {r.api_base}
        </span>
      ),
    },
    { key: 'request_size', header: '单请求条数', width: 106, align: 'right', hideOnMobile: true, cell: (r) => <span style={{ fontVariantNumeric: 'tabular-nums' }}>{r.request_size}</span> },
    { key: 'is_enabled', header: '启用', width: 76, cell: (r) => <EnableSwitch checked={r.is_enabled} disabled={!canManage} onToggle={() => onToggle(r)} /> },
    { key: 'created_by_username', header: '创建人', width: 96, hideOnMobile: true, cell: (r) => r.created_by_username || <span style={{ color: 'var(--fg-subtle)' }}>-</span> },
    { key: 'updated_at', header: '更新时间', width: 168, sortable: true, hideOnMobile: true, cell: (r) => <TimeCell value={r.updated_at} /> },
    {
      key: 'actions', header: '操作', width: 200, pinRight: true,
      cell: (r) => (
        <span className="inline-flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
          <Button size="sm" variant="secondary" onClick={() => onTest(r)}>{testingId === r.id ? '测试中…' : '测试'}</Button>
          <Button size="sm" variant="secondary" disabled={!canManage} onClick={() => onEdit(r)}>编辑</Button>
          <InlineConfirm message="确定删除？绑定了它的知识库将无法入库与检索" danger onConfirm={() => onDelete(r)}>
            <Button size="sm" variant="danger" disabled={!canManage}>删除</Button>
          </InlineConfirm>
        </span>
      ),
    },
  ]
}
