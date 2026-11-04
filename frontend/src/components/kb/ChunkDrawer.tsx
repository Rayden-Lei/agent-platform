import { useEffect, useState } from 'react'
import { cn } from 'cn'
import { listDocChunks, type ChunkRow, type DocumentRow } from '../../api'
import { usePagedList } from '../../hooks/usePagedList'
import { Skeleton } from '@/components/shadcn/skeleton'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import EmptyState from '../common/EmptyState'

// 切片抽屉（详情页上唯一一层抽屉）：分页看某文档的切片、token 数与入库时的向量后端。
// 切片是长文本列表、不是表格，所以自己渲染列表 + 简单翻页，不套 DataTable。
interface Props { kbId: number; doc: DocumentRow | null; onClose: () => void }

const PAGE_SIZE = 20
// 折叠时正文露出的行数；超过就出现"展开"
const CLAMP = 4

export default function ChunkDrawer({ kbId, doc, onClose }: Props) {
  const [expanded, setExpanded] = useState<number[]>([])
  // auto 关掉：打开与切换文档都从第 1 页重新取，统一由下面这个 effect 触发（否则换文档时会沿用上一篇的切片）
  const list = usePagedList<ChunkRow>((params) => listDocChunks(kbId, doc?.id ?? 0, params), { pageSize: PAGE_SIZE, auto: false })
  useEffect(() => {
    if (!doc) return
    setExpanded([])
    list.load(1, PAGE_SIZE)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc?.id])

  const totalPages = Math.max(1, Math.ceil(list.total / list.pageSize))
  const offset = (list.page - 1) * list.pageSize
  const toggle = (id: number) => setExpanded((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]))

  return (
    <Drawer title={doc ? `切片：${doc.name}（共 ${list.total} 个）` : ''} open={!!doc} onClose={onClose} width={720}>
      <div className="flex flex-col gap-3">
        {list.loading && list.items.length === 0 ? (
          <div className="flex flex-col gap-3.5">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex flex-col gap-2">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
              </div>
            ))}
          </div>
        ) : list.items.length === 0 ? (
          <EmptyState description="该文档没有切片" />
        ) : (
          <ul className="m-0 list-none p-0">
            {list.items.map((c, idx) => {
              const open = expanded.includes(c.id)
              const long = c.content.split('\n').length > CLAMP || c.content.length > 320
              return (
                <li key={c.id} className="border-b border-border py-3 first:pt-0 last:border-b-0">
                  <div className="mb-1.5 flex items-start justify-between gap-2">
                    <span className="text-[13px] font-semibold">#{offset + idx + 1}</span>
                    <span className="flex flex-wrap items-center justify-end gap-1.5">
                      <Badge tone="info">{c.token_count ?? 0} tokens</Badge>
                      {/* 入库时的向量后端：hash 表示这批切片是降级入库的，换回真实模型后需要重新解析 */}
                      {c.meta?.embedding_mode === 'hash' && <Badge tone="warning">hash 向量</Badge>}
                      {c.meta?.embedding_mode === 'model' && <Badge tone="success">{String(c.meta.embedding_model)}</Badge>}
                    </span>
                  </div>
                  <p className={cn('m-0 whitespace-pre-wrap text-[13px] leading-relaxed text-foreground', !open && 'line-clamp-4')}>{c.content}</p>
                  {long && (
                    <Button size="sm" variant="ghost" className="mt-1" onClick={() => toggle(c.id)}>{open ? '收起' : '展开'}</Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        {list.total > PAGE_SIZE && (
          <div className="flex shrink-0 items-center justify-between gap-2 pt-1">
            <span className="text-[12px] text-muted-foreground">共 {list.total} 个切片</span>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="secondary" disabled={list.page <= 1} onClick={() => list.load(list.page - 1, list.pageSize)}>上一页</Button>
              <span className="px-1 text-[12px] text-muted-foreground">{list.page} / {totalPages}</span>
              <Button size="sm" variant="secondary" disabled={list.page >= totalPages} onClick={() => list.load(list.page + 1, list.pageSize)}>下一页</Button>
            </div>
          </div>
        )}
      </div>
    </Drawer>
  )
}
