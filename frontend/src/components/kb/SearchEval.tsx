import { useState } from 'react'
import { Button, Descriptions, Input, InputNumber, Tag, Typography, message } from 'antd'
import { SearchOutlined } from '@ant-design/icons'
import { searchKB, type SearchHit, type SearchStats } from '../../api'
import EmptyState from '../common/EmptyState'
import HitCard, { type HitLocation } from '../trace/HitCard'
import { errorText } from '../../utils/errors'

const { Text } = Typography

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
          { key: 'timings', label: '耗时', span: 4, children: stats.timings ? <Text type="secondary" style={{ fontSize: 12 }}>向量化 {stats.timings.embed_ms ?? '-'} ms · 向量召回 {stats.timings.vector_ms ?? '-'} ms · 关键词召回 {stats.timings.keyword_ms ?? '-'} ms（{stats.timings.keyword_count ?? 0} 个词）· 重排 {stats.timings.rerank_ms ?? '-'} ms</Text> : '—' },
        ]} />
      )}
      {searched && results.length === 0 ? (
        <EmptyState description={stats?.kb_denied ? '当前角色无权检索这个知识库：按知识库当前的访问权限判定，调用者用绑定它的智能体对话时同样拿不到引用' : '没有命中片段：可能是文档尚未就绪、权限过滤剔除了全部候选，或检索词与文档内容差距较大'} />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {results.map((r, idx) => (
            <HitCard key={r.chunk_id ?? idx} rank={idx + 1} docName={r.doc_name} docId={r.doc_id} score={r.score} content={r.content}
              vectorScore={r.vector_score} keywordScore={r.keyword_score} rerankScore={r.rerank_score} matchedKeywords={r.matched_keywords}
              location={r.meta as HitLocation} />
          ))}
        </div>
      )}
    </div>
  )
}
