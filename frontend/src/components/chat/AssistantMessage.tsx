import { Button, Space, Typography } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'
import AnswerMarkdown from './AnswerMarkdown'
import ContextCards from './ContextCards'
import ThinkingTrace from './ThinkingTrace'
import ToolChips from './ToolChips'
import type { ChatCapabilities, Msg } from './types'
import { copyText } from '../../utils/clipboard'
import { formatCost, formatNumber } from '../../utils/format'
import { formatDuration, fromNow } from '../../utils/time'

const { Text } = Typography

// 助手消息气泡：按“思考过程 → 工具调用 → 回答正文 → 引用来源卡片 → 脚注（Token 用量 / 时间 / 复制 / 运行记录）”的顺序拼装；
// streaming 为 true 且正文为空时展示“思考中…”占位。能看到哪些过程信息由 capabilities 决定（D-19），组件本身不读登录态，
// 登录对话页、装配页调试、分享访客页各自传入
interface Props { msg: Msg; streaming?: boolean; capabilities: ChatCapabilities; onShowDetails?: (msg: Msg) => void }

export default function AssistantMessage({ msg, streaming, capabilities, onShowDetails }: Props) {
  const hasContent = msg.content.length > 0
  // http 下没有剪贴板：此前 navigator.clipboard 为空时点了没有任何反应，现在会提示手动复制
  const copy = () => copyText(msg.content)
  const usageText = capabilities.showUsage && msg.usage?.total_tokens
    ? `Token ${formatNumber(msg.usage.total_tokens)}（输入 ${formatNumber(msg.usage.prompt_tokens ?? 0)} / 输出 ${formatNumber(msg.usage.completion_tokens ?? 0)}）`
    : ''
  // 调试脚注：首字 / 总耗时 / 检索耗时 / 成本，数值来自 done 事件（与运行记录一致）
  const m = capabilities.showDebugMeta ? msg.metrics : undefined
  const debugText = m
    ? [m.first_token_ms != null ? `首字 ${formatDuration(m.first_token_ms)}` : '', `总 ${formatDuration(m.latency_ms)}`,
      m.retrieval_ms ? `检索 ${formatDuration(m.retrieval_ms)}` : '', m.cost != null ? `成本 ${formatCost(m.cost)}` : ''].filter(Boolean).join(' · ')
    : ''

  return (
    <div className="assistant-msg">
      {/* 思考过程时间线：检索命中条数 + 工具步骤 + 生成回答（只有步骤与状态，不含工具入参与片段内容） */}
      <ThinkingTrace citations={msg.citations} tools={msg.tools} running={streaming} />
      {/* 工具调用标签条；showToolDetails 关掉时只显示工具名 */}
      <ToolChips tools={msg.tools} showDetails={capabilities.showToolDetails} />
      {hasContent ? (
        <AnswerMarkdown content={msg.content} citations={capabilities.showCitations ? msg.citations : undefined} />
      ) : streaming ? (
        <div className="assistant-typing">思考中…</div>
      ) : null}
      {capabilities.showCitations && <ContextCards citations={msg.citations} />}
      {!streaming && (hasContent || msg.usage) && (
        <div className="usage-footer" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {debugText && <>{debugText}<br /></>}
            {usageText}
            {msg.createdAt ? `${usageText ? ' · ' : ''}${fromNow(msg.createdAt)}` : ''}
          </Text>
          <Space size={4}>
            {capabilities.showDebugMeta && onShowDetails && (msg.trace?.length || msg.prompt) && <Button size="small" type="link" onClick={() => onShowDetails(msg)}>详情</Button>}
            {msg.runId && capabilities.showRunLink && <Link to={`/runs/${msg.runId}`} style={{ fontSize: 12 }}>运行记录</Link>}
            <Button size="small" type="text" icon={<CopyOutlined />} onClick={copy} aria-label="复制回答" title="复制回答" />
          </Space>
        </div>
      )}
    </div>
  )
}
