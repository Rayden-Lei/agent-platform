import { Card, Tag, Typography } from 'antd'
import { FileTextOutlined } from '@ant-design/icons'
import type { Citation } from './types'

const { Paragraph } = Typography

// 引用来源卡片区：把回答命中的知识库片段逐条列成卡片，展示文档名、相关度与内容摘要；
// 没有引用时返回 null 不渲染
export default function ContextCards({ citations }: { citations?: Citation[] }) {
  if (!Array.isArray(citations) || citations.length === 0) return null

  return (
    <div className="context-cards">
      <div className="context-cards-header">
        <FileTextOutlined /> 引用来源（{citations.length}）
      </div>
      {citations.map((c, i) => (
        <Card
          key={i}
          size="small"
          className="context-card"
          title={
            <span className="context-card-title">
              <span className="context-card-index">[{i + 1}]</span>
              {c.doc_name || '文档 ' + (i + 1)}
            </span>
          }
          extra={
            typeof c.score === 'number' ? (
              <Tag color="blue" style={{ marginInlineEnd: 0 }}>相关度 {c.score.toFixed(2)}</Tag>
            ) : null
          }
        >
          {/* 内容最多展示 2 行，可点击“展开”查看全文 */}
          <Paragraph
            style={{ marginBottom: 0, fontSize: 12.5, color: '#475569' }}
            ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
          >
            {c.content || '无内容'}
          </Paragraph>
        </Card>
      ))}
    </div>
  )
}
