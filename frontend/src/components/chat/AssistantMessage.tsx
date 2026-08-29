import { Typography } from 'antd'
import AnswerMarkdown from './AnswerMarkdown'
import ContextCards from './ContextCards'
import ThinkingTrace from './ThinkingTrace'
import ToolChips from './ToolChips'
import type { Msg } from './types'

const { Text } = Typography

export default function AssistantMessage({ msg, streaming }: { msg: Msg; streaming?: boolean }) {
  const hasContent = msg.content.length > 0

  return (
    <div className="assistant-msg">
      <ThinkingTrace citations={msg.citations} tools={msg.tools} running={streaming} />
      <ToolChips tools={msg.tools} />
      {hasContent ? (
        <AnswerMarkdown content={msg.content} citations={msg.citations} />
      ) : streaming ? (
        <div className="assistant-typing">思考中…</div>
      ) : null}
      <ContextCards citations={msg.citations} />
      {msg.usage && (
        <div className="usage-footer">
          <Text type="secondary">
            Token 用量 {msg.usage.total_tokens}（输入 {msg.usage.prompt_tokens} / 输出 {msg.usage.completion_tokens}）
          </Text>
        </div>
      )}
    </div>
  )
}
