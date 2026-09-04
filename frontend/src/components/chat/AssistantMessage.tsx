import { Typography } from 'antd'
import AnswerMarkdown from './AnswerMarkdown'
import ContextCards from './ContextCards'
import ThinkingTrace from './ThinkingTrace'
import ToolChips from './ToolChips'
import type { Msg } from './types'

const { Text } = Typography

// 助手消息气泡：按“思考过程 → 工具调用 → 回答正文 → 引用来源卡片 → Token 用量”的顺序拼装整条消息；
// streaming 为 true 且正文为空时展示“思考中…”占位
export default function AssistantMessage({ msg, streaming }: { msg: Msg; streaming?: boolean }) {
  const hasContent = msg.content.length > 0

  return (
    <div className="assistant-msg">
      {/* 思考过程时间线：检索命中 + 工具步骤 + 生成回答 */}
      <ThinkingTrace citations={msg.citations} tools={msg.tools} running={streaming} />
      {/* 工具调用标签条 */}
      <ToolChips tools={msg.tools} />
      {hasContent ? (
        <AnswerMarkdown content={msg.content} citations={msg.citations} />
      ) : streaming ? (
        <div className="assistant-typing">思考中…</div>
      ) : null}
      {/* 引用来源卡片 */}
      <ContextCards citations={msg.citations} />
      {/* 有 token 统计时展示用量脚注 */}
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
