import { useRef, useState } from 'react'
import { useTheme } from '../../store/theme'
import GlassSurface from '../theme/GlassSurface'

// 输入条：圆角浮岛，底部一排功能位（附件 / 模型名 / 发送）。
// Enter 发送、Shift+Enter 换行；发送中切换为停止。maxLength 与后端 CHAT_MESSAGE_MAX_CHARS 对齐只是体验，
// 超长的权威拒绝在后端（422）。移动端底部叠加安全区（docs/15 CH-14）。
// 输入法组合中按回车是在确认候选词，不发送——rc-textarea 不判断组合态，此前用拼音按回车会发半截拼音。
interface Props {
  disabled?: boolean
  sending: boolean
  onSend: (text: string) => void
  onStop: () => void
  compact?: boolean
  placeholder?: string
  maxLength?: number
  modelName?: string
}

const ICON_ATTACH = (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48" />
  </svg>
)
const ICON_SEND = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
)
const ICON_STOP = (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
)

export default function ChatInput({ disabled, sending, onSend, onStop, compact, placeholder, maxLength, modelName }: Props) {
  const [text, setText] = useState('')
  const glass = useTheme((s) => s.glass)

  const areaRef = useRef<HTMLTextAreaElement>(null)

  const canSend = !!text.trim() && !sending && !disabled
  const send = () => {
    if (!canSend) return
    onSend(text.trim())
    setText('')
    // 发送后回到一行高度
    if (areaRef.current) areaRef.current.style.height = 'auto'
  }

  const pad = compact ? 8 : 12

  return (
    <div
      className="shrink-0"
      style={{ padding: pad, paddingBottom: `calc(${pad}px + env(safe-area-inset-bottom))` }}
    >
      <div
        className="relative"
        style={{ borderRadius: 'var(--radius-lg)', background: glass ? 'transparent' : 'var(--bg-elev)', border: '1px solid var(--border-strong)' }}
      >
        <GlassSurface enabled={glass} cornerRadius={12} />
        <div className="relative" style={{ padding: '10px 12px' }}>
        <textarea
          ref={areaRef}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            setText(e.target.value)
            // 自适应高度：1–6 行
            const el = e.target
            el.style.height = 'auto'
            el.style.height = `${Math.min(el.scrollHeight, 6 * 22 + 16)}px`
          }}
          onKeyDown={(e) => {
            // 组合态（输入法选词）不发送：keyCode 229 覆盖不带 isComposing 的浏览器
            if (e.nativeEvent.isComposing || e.keyCode === 229) return
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
          placeholder={placeholder ?? (disabled ? '请先选择已发布的智能体' : '输入消息，Enter 发送，Shift+Enter 换行')}
          maxLength={maxLength}
          rows={1}
          className="w-full resize-none bg-transparent outline-none text-[13.5px] leading-[22px]"
          style={{ color: 'var(--fg)', maxHeight: 6 * 22 + 16, minHeight: 22 }}
        />

        <div className="flex items-center gap-1.5 mt-2">
          <button
            type="button"
            disabled
            title="附件（暂未开放）"
            aria-label="添加附件"
            className="w-7 h-7 rounded-lg flex items-center justify-center disabled:opacity-40"
            style={{ color: 'var(--fg-muted)' }}
          >
            {ICON_ATTACH}
          </button>
          {modelName && (
            <span className="text-[12px] px-2 py-1 rounded-lg truncate" style={{ color: 'var(--fg-muted)' }} title={modelName}>
              {modelName}
            </span>
          )}

          <span className="ml-auto" />

          {sending ? (
            <button
              type="button"
              onClick={onStop}
              aria-label="停止生成"
              className="w-[30px] h-[30px] rounded-full flex items-center justify-center shrink-0"
              style={{ background: '#DC2626', color: '#fff' }}
            >
              {ICON_STOP}
            </button>
          ) : (
            <button
              type="button"
              onClick={send}
              disabled={!canSend}
              aria-label="发送"
              className="w-[30px] h-[30px] rounded-full flex items-center justify-center shrink-0 transition-opacity disabled:opacity-35"
              style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
            >
              {ICON_SEND}
            </button>
          )}
        </div>
        </div>
      </div>
    </div>
  )
}
