// “思考过程”折叠面板：用 Timeline 展示检索知识库、逐个调用工具、生成回答这几类步骤的进度与结果
import { Collapse, Tag, Timeline, Typography } from 'antd'
import { SearchOutlined, ToolOutlined, FileDoneOutlined } from '@ant-design/icons'
import type { Citation, ToolStep, ToolStepStatus } from './types'

const { Text } = Typography

// 工具步骤状态 → Timeline 节点颜色：运行中蓝、出错红、其余绿
function stepColor(status: ToolStepStatus): string {
  if (status === 'running') return 'blue'
  if (status === 'error') return 'red'
  return 'green'
}

export default function ThinkingTrace({
  citations,
  tools,
  running,
}: {
  citations?: Citation[]
  tools?: ToolStep[]
  running?: boolean
}) {
  const hasCitations = Array.isArray(citations) && citations.length > 0
  const hasTools = Array.isArray(tools) && tools.length > 0
  // 既没有检索也没有工具调用时，该面板没有内容可展示，直接不渲染
  if (!hasCitations && !hasTools) return null

  // 按时间顺序组装 Timeline 节点：检索 → 每个工具调用 → 生成回答
  const items: any[] = []

  if (hasCitations) {
    items.push({
      color: 'blue',
      dot: <SearchOutlined />,
      children: (
        <span>
          检索知识库，命中 <b>{citations!.length}</b> 条相关片段
        </span>
      ),
    })
  }

  ;(tools || []).forEach((t) => {
    items.push({
      color: stepColor(t.status),
      dot: <ToolOutlined />,
      children: (
        <div>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>调用工具 {t.name}</div>
          <div style={{ fontSize: 12, color: '#64748b' }}>
            {t.status === 'running' ? '执行中…' : t.status === 'error' ? '执行出错' : '已完成'}
          </div>
        </div>
      ),
    })
  })

  // 最后一步：回答生成中（灰）或已完成（绿）
  items.push({
    color: running ? 'gray' : 'green',
    dot: <FileDoneOutlined />,
    children: running ? '正在生成回答…' : '已生成回答',
  })

  // 步骤总数 = 检索(0/1) + 工具调用数 + 生成回答(1)，用于标题上的“N 步”标签
  const stepCount = (hasCitations ? 1 : 0) + (hasTools ? tools!.length : 0) + 1

  return (
    <Collapse
      ghost
      size="small"
      className="thinking-trace"
      defaultActiveKey={['trace']}
      items={[
        {
          key: 'trace',
          label: (
            <span className="thinking-label">
              <Text strong>思考过程</Text>
              <Tag style={{ marginInlineStart: 6 }}>{stepCount} 步</Tag>
            </span>
          ),
          children: <Timeline items={items} />,
        },
      ]}
    />
  )
}
