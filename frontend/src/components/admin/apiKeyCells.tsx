import type { ApiKeyRow } from '../../api'
import Badge from '../ui/Badge'
import { formatDateTime } from '../../utils/time'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'

// API Key 的几个展示型单元格：配额、授权范围、过期徽章。
// 从 apiKeyColumns 拆出来是因为列定义文件有自己的行数约定（docs/07 第 9 节：列定义 ≤ 100 行），
// 而这三件同时被列表列、详情抽屉、个人中心与发布渠道的小表复用。

// 配额进度：用量占比 ≥ 90% 标红提醒续配额。
// 三态必须显式区分（docs/15 PB-11）：quota === null 是"不限次数"，quota === 0 是"一次都不许调"，
// 不能用 !quota 判——那样 0 会被显示成"不限"，而服务端对 0 恒返回 429，页面与事实正好相反。
export function QuotaCell({ used, quota }: { used: number; quota: number | null }) {
  if (quota === null) return <span className="text-muted-foreground">{used} / 不限</span>
  if (quota === 0) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-default"><Badge tone="danger">已禁用</Badge></span>
        </TooltipTrigger>
        <TooltipContent>配额为 0：任何调用都会返回 429「配额已用尽」；把配额调高或留空（不限）才能恢复</TooltipContent>
      </Tooltip>
    )
  }
  const ratio = Math.min(used / quota, 1)
  const danger = ratio >= 0.9
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="min-w-[120px] cursor-default">
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full" style={{ width: `${Math.round(ratio * 100)}%`, background: danger ? 'var(--danger)' : 'var(--accent)' }} />
          </div>
          <span className="mt-0.5 block text-[11.5px] text-muted-foreground">{used} / {quota}</span>
        </div>
      </TooltipTrigger>
      <TooltipContent>已用 {used} / 配额 {quota}{danger ? '（快用完了，调高配额或留空改为不限）' : ''}</TooltipContent>
    </Tooltip>
  )
}

// 授权范围（docs/15 3.7.1）：N 个智能体、M 个工作流…，悬停看名称，已删除的资源标"已删除"；三类都空的是迁移前建的，调用一律被拒
const SCOPE_LABELS = [['agents', '智能体'], ['workflows', '工作流'], ['knowledge_bases', '知识库']] as const
export function ScopeCell({ scope }: { scope: ApiKeyRow['scope'] }) {
  const parts = SCOPE_LABELS.filter(([key]) => scope[key].length)
  if (!parts.length) {
    return (
      <Tooltip>
        <TooltipTrigger asChild><span><Badge tone="warning">未授权</Badge></span></TooltipTrigger>
        <TooltipContent>没有授权任何资源（迁移前建的 Key），调用一律被拒；编辑后授权即可</TooltipContent>
      </Tooltip>
    )
  }
  const names = parts.map(([key, label]) => `${label}：${scope[key].map((x) => x.name ?? `已删除 #${x.id}`).join('、')}`)
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-default">{parts.map(([key, label]) => `${scope[key].length} 个${label}`).join('、')}</span>
      </TooltipTrigger>
      <TooltipContent className="whitespace-pre-line">{names.join('\n')}</TooltipContent>
    </Tooltip>
  )
}

// 已过期徽章：与"已停用"分开表达 —— 停用是人为关掉的开关（可以再打开），过期是时间到了（要改有效期才能用）。
// 两者可以同时成立，所以并排显示，不互相顶掉。是否过期一律用服务端下发的 is_expired，前端不自己比时间（时区与时钟都可能不准）。
export function ExpiredBadge({ expiresAt }: { expiresAt: string | null }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span><Badge tone="danger">已过期</Badge></span>
      </TooltipTrigger>
      <TooltipContent>
        {expiresAt ? `已于 ${formatDateTime(expiresAt)} 过期` : '已过期'}；调用返回 401「API Key 已过期」且不消耗配额，编辑有效期或清除有效期即可恢复
      </TooltipContent>
    </Tooltip>
  )
}
