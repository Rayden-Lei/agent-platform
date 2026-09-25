// 工具调用标签条：每个工具一个 Tag（点击展开参数/结果详情），颜色与图标随执行状态变化
import { Popover, Space, Tag, Typography } from 'antd'
import { LoadingOutlined, ToolOutlined } from '@ant-design/icons'
import type { ToolStep, ToolStepStatus } from './types'

const { Text } = Typography

// 工具步骤状态 → antd Tag 颜色：运行中 processing、出错 error、其余 success
function tagColor(status: ToolStepStatus): string {
  if (status === 'running') return 'processing'
  if (status === 'error') return 'error'
  return 'success'
}

// 工具详情的悬浮内容：格式化展示调用参数与返回结果
function ToolDetail({ tool }: { tool: ToolStep }) {
  return (
    <div style={{ maxWidth: 380, minWidth: 260 }}>
      <div style={{ marginBottom: 8 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>参数</Text>
        <pre className="tool-detail-pre">{JSON.stringify(tool.args ?? {}, null, 2)}</pre>
      </div>
      <div>
        <Text type="secondary" style={{ fontSize: 12 }}>结果</Text>
        <div className="tool-detail-result">
          {tool.status === 'running' ? '执行中…' : (tool.result || '（无返回值）')}
        </div>
      </div>
    </div>
  )
}

// 主组件：无工具调用时不渲染；showDetails 时每个 Tag 点击后以 Popover 展示该步骤的参数与结果，
// 否则只显示工具名（调用者不看工具入参：可能含内部地址，docs/15 D-19）
export default function ToolChips({ tools, showDetails }: { tools?: ToolStep[]; showDetails: boolean }) {
  if (!Array.isArray(tools) || tools.length === 0) return null

  return (
    <Space size={[6, 6]} wrap className="tool-chips">
      {tools.map((t, i) => {
        const tag = (
          <Tag
            key={i}
            color={tagColor(t.status)}
            icon={t.status === 'running' ? <LoadingOutlined /> : <ToolOutlined />}
            className="tool-chip"
          >
            {t.name}
          </Tag>
        )
        return showDetails ? <Popover key={i} trigger="click" placement="bottom" title={t.name} content={<ToolDetail tool={t} />}>{tag}</Popover> : tag
      })}
    </Space>
  )
}
