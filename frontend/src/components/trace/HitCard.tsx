import { Card, Space, Tag, Typography } from 'antd'

const { Paragraph, Text } = Typography

// 检索命中卡片：知识库"检索评测"与装配页调试的"召回"共用（docs/15 3.4）。
// 正文可选：调试的检索步骤不重复带正文，由调用方按 chunk_id 从引用里补；定位信息来自切片 meta（页码 / 行号 / 标题）。
export interface HitLocation { type?: string; page?: number; row?: number; heading?: string }
interface Props {
  rank: number
  docName?: string | null
  docId?: number | null
  score: number
  content?: string
  vectorScore?: number | null
  keywordScore?: number | null
  rerankScore?: number | null
  matchedKeywords?: string[]
  location?: HitLocation
}

export function locationText(loc?: HitLocation): string {
  if (!loc) return ''
  if (loc.page != null) return `第 ${loc.page} 页`
  if (loc.row != null) return `第 ${loc.row} 行`
  return loc.heading ? `标题：${loc.heading}` : ''
}

export default function HitCard({ rank, docName, docId, score, content, vectorScore, keywordScore, rerankScore, matchedKeywords, location }: Props) {
  const where = locationText(location)
  return (
    <Card size="small" title={
      <Space size={8} wrap>
        <Tag color="blue">#{rank}</Tag>
        <Text strong>{docName || '文档 ' + (docId ?? '?')}</Text>
        {where && <Text type="secondary" style={{ fontSize: 12 }}>{where}</Text>}
        <Text type="secondary" style={{ fontSize: 12 }}>score {score.toFixed(4)}</Text>
      </Space>
    }>
      {content && <Paragraph style={{ marginBottom: 8, fontSize: 13 }} ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>{content}</Paragraph>}
      {typeof vectorScore === 'number' && (
        <Space size={6} wrap>
          <Tag>向量 {vectorScore}</Tag>
          <Tag>词法 {keywordScore}</Tag>
          {typeof rerankScore === 'number' && <Tag color="success">重排 {rerankScore.toFixed(4)}</Tag>}
          {(matchedKeywords || []).map((k) => <Tag key={k} color="cyan">{k}</Tag>)}
        </Space>
      )}
    </Card>
  )
}
