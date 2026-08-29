import { Popover, Space, Tag, Typography } from 'antd'
import { LoadingOutlined, ToolOutlined } from '@ant-design/icons'
import type { ToolStep, ToolStepStatus } from './types'

const { Text } = Typography

function tagColor(status: ToolStepStatus): string {
  if (status === 'running') return 'processing'
  if (status === 'error') return 'error'
  return 'success'
}

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

export default function ToolChips({ tools }: { tools?: ToolStep[] }) {
  if (!Array.isArray(tools) || tools.length === 0) return null

  return (
    <Space size={[6, 6]} wrap className="tool-chips">
      {tools.map((t, i) => (
        <Popover key={i} trigger="click" placement="bottom" title={t.name} content={<ToolDetail tool={t} />}>
          <Tag
            color={tagColor(t.status)}
            icon={t.status === 'running' ? <LoadingOutlined /> : <ToolOutlined />}
            className="tool-chip"
          >
            {t.name}
          </Tag>
        </Popover>
      ))}
    </Space>
  )
}
