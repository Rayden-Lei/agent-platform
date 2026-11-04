import { useState } from 'react'
import { Eraser, PanelRightClose } from 'lucide-react'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import Button from '../../ui/Button'
import ChatPanel from '../../chat/ChatPanel'
import { CHAT_MESSAGE_MAX_CHARS, DEBUG_CAPABILITIES, type Msg } from '../../chat/types'
import DebugDetailDrawer from './DebugDetailDrawer'

// 装配页右栏的调试面板（docs/15 3.4，FR-041）：调试对象是编辑器当前内容（含未保存修改），不用保存就能试。
// 调试历史只在页面里、不进会话列表；运行记录记 source=debug，运营统计不计，模型消耗照常计入。
// 只接收 props 与回调：发送与流式状态在 hooks/useAgentDebug，由装配页注入（07 第 2、9 节）。
interface Props {
  messages: Msg[]
  sending: boolean
  compact: boolean
  onSend: (text: string) => void
  onStop: () => void
  onRegenerate: () => void
  onClear: () => void
  onCollapse?: () => void
}

export default function DebugPanel({ messages, sending, compact, onSend, onStop, onRegenerate, onClear, onCollapse }: Props) {
  const [detail, setDetail] = useState<Msg | null>(null)
  const header = (
    <>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-[13.5px] font-medium text-foreground">
          调试 <span className="text-[12px] font-normal text-muted-foreground">对象：编辑器当前内容（含未保存修改）</span>
        </span>
        <span className="text-[12px] text-muted-foreground">引用的工具、知识库、模型本身的修改不经发布，立即影响线上</span>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" aria-label="清空调试记录" disabled={sending || !messages.length} onClick={onClear}>
            <Eraser className="size-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent>清空调试记录，重新开始</TooltipContent>
      </Tooltip>
      {onCollapse && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="ghost" size="sm" aria-label="收起调试区" onClick={onCollapse}>
              <PanelRightClose className="size-3.5" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>收起调试区</TooltipContent>
        </Tooltip>
      )}
    </>
  )
  return (
    <>
      <ChatPanel header={header} messages={messages} sending={sending} isMobile={compact} maxLength={CHAT_MESSAGE_MAX_CHARS} capabilities={DEBUG_CAPABILITIES}
        emptyHint="改完左侧配置直接在这里提问，不用保存。每轮都真实调用模型（计入模型消耗），不进会话列表，运营统计不计。"
        onSend={onSend} onStop={onStop} onRegenerate={onRegenerate} onShowDetails={setDetail} />
      <DebugDetailDrawer msg={detail} onClose={() => setDetail(null)} />
    </>
  )
}
