import { Skeleton } from '@/components/shadcn/skeleton'
import type { LoginRecord } from '../../api'
import ErrorState from '../common/ErrorState'
import TimeCell from '../common/TimeCell'
import Badge from '../ui/Badge'

// 个人中心"登录记录"（docs/15 OP-03）：近 90 天最近 20 次，含用你的用户名输错密码的尝试——看到不认识的来源 IP 就该改密并退出其他设备。
// 数据由页面传入。固定几行的小表，用原生 table。
interface Props { rows: LoginRecord[] | null; error?: string | null; onRetry: () => void }

const HEADERS = ['时间', '来源 IP', '结果']

export default function LoginHistoryTable({ rows, error, onRetry }: Props) {
  if (error) return <ErrorState compact message={error} onRetry={onRetry} />
  return (
    <div className="flex max-w-[560px] flex-col gap-2">
      <p className="m-0 text-[12.5px] leading-relaxed text-muted-foreground">
        近 90 天最近 20 次登录，包括用你的用户名输错密码的尝试。看到不认识的来源，请修改密码并退出其他设备。
      </p>
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
            {!rows && [0, 1, 2].map((i) => (
              <tr key={i} className="border-t border-border">
                {HEADERS.map((h) => (
                  <td key={h} className="px-3 py-2.5"><Skeleton className="h-3.5 w-full" /></td>
                ))}
              </tr>
            ))}
            {rows && rows.length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={HEADERS.length} className="px-3 py-4 text-center text-[12.5px] text-muted-foreground">还没有登录记录</td>
              </tr>
            )}
            {rows && rows.map((r) => (
              <tr key={`${r.created_at}-${r.success}`} className="border-t border-border">
                <td className="px-3 py-2.5"><TimeCell value={r.created_at} /></td>
                <td className="px-3 py-2.5">{r.ip || <span className="text-muted-foreground">-</span>}</td>
                <td className="px-3 py-2.5">{r.success ? <Badge tone="success">成功</Badge> : <Badge tone="danger">密码错误</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
