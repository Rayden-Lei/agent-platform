import { Skeleton } from '@/components/shadcn/skeleton'
import type { KbAccessChange, KbAccessInput } from '../../api'
import { statusLabel } from '../../constants/status'
import { formatDateTime } from '../../utils/time'
import EmptyState from '../common/EmptyState'
import ErrorState from '../common/ErrorState'

// 访问权限的变更记录（新的在前）：谁、什么时候、从什么改成什么。只接收 props。
interface Props {
  changes: KbAccessChange[] | null
  total?: number
  error?: string | null
  onRetry: () => void
}

const describe = (p: KbAccessInput | null) => {
  if (!p) return ''
  if (p.is_public) return '公开'
  const roles = p.visible_roles.filter((r) => r !== 'admin').map((r) => statusLabel('role', r))
  return roles.length ? `仅管理员与${roles.join('、')}` : '仅管理员'
}

export default function KbAccessLog({ changes, total, error, onRetry }: Props) {
  const shown = changes?.length ?? 0
  return (
    <section className="rounded-xl border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <h3 className="m-0 text-[13.5px] font-semibold">变更记录</h3>
        {total !== undefined && total > shown && (
          <span className="text-[12.5px] text-muted-foreground">显示最近 {shown} 条，共 {total} 条</span>
        )}
      </div>
      <div className="px-4 py-3">
        {error ? <ErrorState compact message={error} onRetry={onRetry} /> : !changes ? (
          <div className="flex flex-col gap-2">
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        ) : changes.length === 0 ? (
          <EmptyState description="还没有记录：2026-10-05 起记录建库与每次修改，之前建的库从下一次修改开始有记录" />
        ) : (
          <ul className="m-0 list-none p-0">
            {changes.map((c) => (
              <li key={c.id} className="flex flex-wrap items-center gap-3 border-b border-border py-2 text-[13.5px] last:border-b-0">
                <span className="text-[12.5px] text-muted-foreground">{formatDateTime(c.created_at)}</span>
                <span className="font-medium">{c.username || '-'}</span>
                <span>{c.action === 'create' ? `建库，初始为${describe(c.after)}` : `${describe(c.before)} → ${describe(c.after)}`}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}
