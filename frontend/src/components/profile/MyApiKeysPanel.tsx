import { Info } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Alert, AlertDescription } from '@/components/shadcn/alert'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { ApiKeyRow } from '../../api'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { QuotaCell, ScopeCell } from '../admin/apiKeyColumns'
import { KEY_PLACEHOLDER } from '../publish/apiSnippets'

// 个人中心"我的 API 密钥"（docs/15 OP-03、D-15）：归属本人的 Key，只读。admin / developer 去「API Key 管理」生成与启停；
// 调用者看到的是管理员代发给自己的，要停用或换新找管理员。示例一律用占位符，页面上不出现明文。数据由页面传入。
// 固定几行的小表，用原生 table，不引 DataTable（没有分页与排序）。
interface Props {
  keys: ApiKeyRow[] | null
  total?: number
  error?: string | null
  onRetry: () => void
  canManage: boolean
  apiBase: string // 对外地址 + /api/v1
}

const HEADERS = ['名称', 'Key 前缀', '状态', '授权范围', '配额 / 已用', '最后使用']

export default function MyApiKeysPanel({ keys, total, error, onRetry, canManage, apiBase }: Props) {
  if (error) return <ErrorState compact message={error} onRetry={onRetry} />
  const example = `curl -N ${apiBase}/agents/<智能体 ID>/chat \\\n  -H "Authorization: Bearer ${KEY_PLACEHOLDER}" \\\n  -H "Content-Type: application/json" \\\n  -d '{"message": "你好"}'`

  return (
    <div className="flex w-full flex-col gap-3">
      <Alert className="border-border-strong">
        <Info className="text-muted-foreground" />
        <AlertDescription>
          {canManage
            ? <>生成、编辑、启停在 <Link to="/api-keys" className="text-primary hover:underline">API Key 管理</Link>；这里只列归属你的 Key。</>
            : '这些 Key 由管理员发放给你：只能调用授权范围内的智能体，要停用或换新请联系管理员。明文只在发放时显示一次，丢了只能重发。'}
        </AlertDescription>
      </Alert>

      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full border-collapse text-[13.5px]">
          <thead className="bg-secondary">
            <tr>
              {HEADERS.map((h) => (
                <th key={h} className="px-3 py-2 text-left text-[12.5px] font-medium text-muted-foreground">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {!keys && [0, 1, 2].map((i) => (
              <tr key={i} className="border-t border-border">
                {HEADERS.map((h) => (
                  <td key={h} className="px-3 py-2.5"><Skeleton className="h-3.5 w-full" /></td>
                ))}
              </tr>
            ))}
            {keys && keys.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={HEADERS.length}>
                  <EmptyState description={canManage ? '还没有归属你的 Key' : '管理员还没有给你发放 API Key'} />
                </td>
              </tr>
            )}
            {keys && keys.map((r) => (
              <tr key={r.id} className="border-t border-border">
                <td className="px-3 py-2.5">
                  {canManage ? <Link to={`/api-keys?open=${r.id}`} className="text-primary hover:underline">{r.name}</Link> : r.name}
                </td>
                <td className="px-3 py-2.5"><code className="font-mono text-[12.5px]">{r.key_prefix}</code></td>
                <td className="px-3 py-2.5"><StatusTag domain="enabled" value={r.is_enabled} /></td>
                <td className="px-3 py-2.5"><ScopeCell scope={r.scope} /></td>
                <td className="px-3 py-2.5"><QuotaCell used={r.used} quota={r.quota} /></td>
                <td className="px-3 py-2.5"><TimeCell value={r.last_used_at} mode="relative" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {total !== undefined && keys && total > keys.length && (
        <p className="m-0 text-[12px] text-muted-foreground">只显示最近 {keys.length} 个（共 {total} 个）</p>
      )}

      <div className="flex flex-col gap-1">
        <p className="m-0 text-[12px] text-muted-foreground">调用示例（把 {KEY_PLACEHOLDER} 换成你的 Key，只在服务端调用）：</p>
        <pre className="m-0 overflow-auto rounded-lg border border-border bg-secondary px-3 py-2.5 font-mono text-[12px] leading-relaxed text-foreground">{example}</pre>
      </div>
    </div>
  )
}
