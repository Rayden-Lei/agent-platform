import { ArrowLeft, Loader2, MoreHorizontal, Rocket, Save } from 'lucide-react'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/shadcn/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import type { AgentDetail } from '../../../api'
import Badge from '../../ui/Badge'
import Button from '../../ui/Button'
import StatusTag from '../../common/StatusTag'

// 装配页顶栏（钉死）：返回、名称与状态（草稿 / 线上 vN / 未发布修改 / 未保存）、保存、发布、更多（去详情、下线、删除）。
// 发布的是已保存的草稿，有未保存修改时先保存。
interface Props {
  agent: AgentDetail
  dirty: boolean
  saving: boolean
  compact: boolean
  onBack: () => void
  onSave: () => void
  onPublish: () => void
  onOpenDetail: () => void
  onOffline: () => void
  onDelete: () => void
}

export default function EditorHeader({ agent, dirty, saving, compact, onBack, onSave, onPublish, onOpenDetail, onOffline, onDelete }: Props) {
  const canPublish = agent.status !== 'published' || agent.has_unpublished_changes
  const publishLabel = agent.status === 'offline' && !agent.has_unpublished_changes ? '重新上线' : '发布'
  return (
    <div className="flex shrink-0 items-center justify-between gap-3 rounded-xl border border-border bg-card px-3.5 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <Button variant="secondary" size="sm" aria-label="返回" onClick={onBack}>
          <ArrowLeft className="size-3.5" />
          {compact ? '' : '返回'}
        </Button>
        <span className="truncate text-[15px] font-semibold text-foreground" style={{ maxWidth: compact ? 120 : 280 }}>{agent.name}</span>
        <StatusTag domain="agent" value={agent.status} />
        {!compact && agent.published_version && <Badge tone="neutral">线上 v{agent.published_version}</Badge>}
        {!compact && agent.has_unpublished_changes && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span><Badge tone="warning">未发布修改</Badge></span>
            </TooltipTrigger>
            <TooltipContent>已保存的草稿与线上版本不同，发布后对外生效</TooltipContent>
          </Tooltip>
        )}
        {dirty && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span><Badge tone="danger">未保存</Badge></span>
            </TooltipTrigger>
            <TooltipContent>浏览器的后退键不会提示，离开前先保存</TooltipContent>
          </Tooltip>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <Button variant={dirty ? 'primary' : 'secondary'} size="sm" disabled={saving} onClick={onSave}>
          {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
          {compact ? '' : saving ? '保存中…' : '保存草稿'}
        </Button>
        <Tooltip>
          <TooltipTrigger asChild>
            <span>
              <Button variant={dirty ? 'secondary' : 'primary'} size="sm" disabled={dirty || !canPublish} onClick={onPublish}>
                <Rocket className="size-3.5" />
                {compact ? '' : publishLabel}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent>{dirty ? '有未保存的修改：发布的是已保存的草稿，先保存' : canPublish ? publishLabel : '草稿与线上一致，无需发布'}</TooltipContent>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="secondary" size="sm" aria-label="更多操作"><MoreHorizontal className="size-3.5" /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onOpenDetail}>去详情页</DropdownMenuItem>
            {agent.status === 'published' && <DropdownMenuItem onSelect={onOffline}>下线</DropdownMenuItem>}
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onSelect={onDelete}>删除</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
