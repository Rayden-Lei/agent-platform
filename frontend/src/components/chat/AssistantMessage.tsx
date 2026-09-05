import { Button, Space, Typography, message } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import AnswerMarkdown from './AnswerMarkdown'
import ContextCards from './ContextCards'
import ThinkingTrace from './ThinkingTrace'
import ToolChips from './ToolChips'
import type { Msg } from './types'
import { formatNumber } from '../../utils/format'
import { fromNow } from '../../utils/time'

const { Text } = Typography

// 助手消息气泡：按“思考过程 → 工具调用 → 回答正文 → 引用来源卡片 → 脚注（Token 用量 / 时间 / 复制 / 运行记录）”的顺序拼装；
// streaming 为 true 且正文为空时展示“思考中…”占位
export default function AssistantMessage({ msg, streaming }: { msg: Msg; streaming?: boolean }) {
  const hasContent = msg.content.length > 0
  const copy = () => navigator.clipboard?.writeText(msg.content).then(() => message.success('已复制'))

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
      {!streaming && (hasContent || msg.usage) && (
        <div className="usage-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {msg.usage?.total_tokens ? `Token ${formatNumber(msg.usage.total_tokens)}（输入 ${formatNumber(msg.usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(msg.usage.completion_tokens ?? 0)}）` : ''}
            {msg.createdAt ? `${msg.usage?.total_tokens ? ' · ' : ''}${fromNow(msg.createdAt)}` : ''}
          </Text>
          <Space size={4}>
            {msg.runId && <Link to={`/runs/${msg.runId}`} style={{ fontSize: 12 }}>运行记录</Link>}
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={copy} />
          </Space>
        </div>
      )}
    </div>
  )
}
