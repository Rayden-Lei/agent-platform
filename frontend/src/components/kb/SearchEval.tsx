import { useState } from 'react'
import { Button, Card, Descriptions, Input, InputNumber, Space, Tag, Typography, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { searchKB, type SearchHit, type SearchStats } from '../../api'
import EmptyState from '../common/EmptyState'
import { errorText } from '../../utils/errors'

const { Paragraph, Text } = Typography

// 检索评测：带 debug 统计的库内检索，看候选数 / 鉴权剔除 / 词法命中 / 分数分布与每条命中的向量 / 词法得分。
interface Props { kbId: number }

export default function SearchEval({ kbId }: Props) {
  const [query, setQuery] = useState('')
  const [topK, setTopK] = useState(5)
  const [results, setResults] = useState<SearchHit[]>([])
  const [stats, setStats] = useState<SearchStats | null>(null)
  const [searching, setSearching] = useState(false)
  const [searched, setSearched] = useState(false)

  const doSearch = async () => {
    if (!query.trim()) return
    setSearching(true)
    try {
      const res = await searchKB(kbId, { query, top_k: topK, debug: true })
      setResults(res.items || [])
      setStats(res.stats || null)
      setSearched(true)
    } catch (e) { message.error(errorText(e, '检索失败')) } finally { setSearching(false) }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="输入检索内容，看命中片段与分数" onPressEnter={doSearch} style={{ flex: 1 }} />
        <Text type="secondary">Top K</Text>
        <InputNumber min={1} max={50} value={topK} onChange={(v) => setTopK(v ?? 5)} style={{ width: 80 }} />
        <Button type="primary" icon={<SearchOutlined />} loading={searching} onClick={doSearch}>检索</Button>
      </div>
      {stats && (
        <Descriptions size="small" bordered column={4} items={[
          { key: 'keywords', label: '关键词', span: 4, children: stats.keywords?.length ? stats.keywords.map((k) => <Tag key={k} color="cyan">{k}</Tag>) : '—' },
          { key: 'candidate_count', label: '候选数', children: stats.candidate_count },
          { key: 'returned', label: '返回数', children: stats.returned },
          { key: 'acl_rejected', label: '鉴权剔除', children: <Text type={stats.acl_rejected ? 'warning' : undefined}>{stats.acl_rejected}</Text> },
          { key: 'lexical_hit_count', label: '词法命中', children: stats.lexical_hit_count },
          { key: 'top_score', label: '最高分', children: <Text strong style={{ color: '#1e40af' }}>{stats.top_score}</Text> },
          { key: 'mean_score', label: '平均分', children: stats.mean_score },
          { key: 'rerank_mode', label: '重排', span: 2, children: stats.rerank_mode === 'model' ? <Tag color="success">重排模型</Tag> : stats.rerank_mode === 'lexical' ? <Tag>词法（未配置或已降级）</Tag> : '—' },
        ]} />
      )}
      {searched && results.length === 0 ? (
        <EmptyState description="没有命中片段：可能是文档尚未就绪、权限过滤剔除了全部候选，或检索词与文档内容差距较大" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {results.map((r, idx) => (
            <Card key={r.chunk_id ?? idx} size="small" title={
              <Space size={8} wrap>
                <Tag color="blue">#{idx + 1}</Tag>
                <Text strong>{r.doc_name || '文档 ' + r.doc_id}</Text>
                <Text type="secondary" style={{ fontSize: 12 }}>score {typeof r.score === 'number' ? r.score.toFixed(4) : r.score}</Text>
              </Space>
            }>
              <Paragraph style={{ marginBottom: 8, fontSize: 13 }} ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>{r.content}</Paragraph>
              {typeof r.vector_score === 'number' && (
                <Space size={6} wrap>
                  <Tag>向量 {r.vector_score}</Tag>
                  <Tag>词法 {r.keyword_score}</Tag>
                  {typeof r.rerank_score === 'number' && <Tag color="success">重排 {r.rerank_score.toFixed(4)}</Tag>}
                  {(r.matched_keywords || []).map((k) => <Tag key={k} color="cyan">{k}</Tag>)}
                </Space>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
