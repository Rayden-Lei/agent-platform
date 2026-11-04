import { MessageSquare, Plus } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import Badge from '../ui/Badge'
import Button from '../ui/Button'

// 分享访客页对话面板的头部：会话抽屉入口、智能体名称与简介、"内容由 AI 生成"、新对话。
// 访客看不到平台任何内部信息，这里的元素只围绕"这个智能体"和"我的会话"。
interface Props {
  name: string
  description?: string | null
  onOpenList: () => void
  onNew: () => void
}

export default function ShareHeader({ name, description, onOpenList, onNew }: Props) {
  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button size="sm" icon={<MessageSquare className="size-3.5" />} onClick={onOpenList} aria-label="我的会话" />
        </TooltipTrigger>
        <TooltipContent>我的会话</TooltipContent>
      </Tooltip>

      <div className="min-w-0 flex-1">
        <span className="block truncate text-[14px] font-semibold text-foreground">{name}</span>
        {description && <span className="block truncate text-[12px] text-muted-foreground">{description}</span>}
      </div>

      <Badge tone="neutral">内容由 AI 生成</Badge>

      <Tooltip>
        <TooltipTrigger asChild>
          <Button size="sm" icon={<Plus className="size-3.5" />} onClick={onNew} aria-label="新对话" />
        </TooltipTrigger>
        <TooltipContent>新对话</TooltipContent>
      </Tooltip>
    </>
  )
}
