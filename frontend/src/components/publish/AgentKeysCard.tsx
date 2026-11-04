import { Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { ApiKeyRow } from '../../api'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import Button from '../ui/Button'
import { QuotaCell } from '../admin/apiKeyColumns'

// "发布渠道"的密钥区（docs/15 3.7.2）：作用域含本智能体的 Key（developer 只看到本人的，服务端过滤）；
// "生成仅限此智能体的 Key"由页面打开预填了作用域的 Key 表单。数据由页面传入，本组件不发请求。
// 固定几行的小表，用原生 table。
interface Props {
  keys: ApiKeyRow[] | null
  total?: number
  error?: string | null
  onRetry: () => void
  onCreate: () => void
}

const HEADERS: { label: string; width?: number }[] = [
  { label: '名称', width: 200 },
  { label: 'Key 前缀', width: 140 },
  { label: '状态', width: 80 },
  { label: '配额 / 已用', width: 170 },
  { label: '最后使用', width: 120 },
]

export default function AgentKeysCard({ keys, total, error, onRetry, onCreate }: Props) {
  return (
    <section className="flex flex-col rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">
          可调用本智能体的密钥{total !== undefined ? `（${total}）` : ''}
        </h3>
        <Button variant="primary" size="sm" icon={<Plus className="size-3.5" />} onClick={onCreate}>生成仅限此智能体的 Key</Button>
      </div>

      <div className="p-3">
        {error ? (
          <ErrorState compact message={error} onRetry={onRetry} />
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <table className="w-full border-collapse text-[13.5px]">
              <thead className="bg-secondary">
                <tr>
                  {HEADERS.map((h) => (
                    <th key={h.label} className="px-3 py-2 text-left text-[12.5px] font-medium text-muted-foreground" style={{ width: h.width }}>{h.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {!keys && [0, 1, 2].map((i) => (
                  <tr key={i} className="border-t border-border">
                    {HEADERS.map((h) => <td key={h.label} className="px-3 py-2.5"><Skeleton className="h-3.5 w-full" /></td>)}
                  </tr>
                ))}
                {keys && keys.length === 0 && (
                  <tr className="border-t border-border">
                    <td colSpan={HEADERS.length}>
                      <EmptyState description="还没有能调用本智能体的 Key；生成一个，交给对接方在服务端使用" />
                    </td>
                  </tr>
                )}
                {keys && keys.map((r) => (
                  <tr key={r.id} className="border-t border-border">
                    <td className="px-3 py-2.5"><Link to={`/api-keys?open=${r.id}`} className="text-primary hover:underline">{r.name}</Link></td>
                    <td className="px-3 py-2.5"><code className="font-mono text-[12.5px]">{r.key_prefix}…</code></td>
                    <td className="px-3 py-2.5"><StatusTag domain="enabled" value={r.is_enabled} /></td>
                    <td className="px-3 py-2.5"><QuotaCell used={r.used} quota={r.quota} /></td>
                    <td className="px-3 py-2.5"><TimeCell value={r.last_used_at} mode="relative" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {total !== undefined && keys && total > keys.length && (
          <p className="mb-0 mt-2 text-[12px] text-muted-foreground">
            显示前 {keys.length} 个，全部见 <Link to="/api-keys" className="text-primary hover:underline">API Key 管理</Link>
          </p>
        )}
      </div>
    </section>
  )
}
