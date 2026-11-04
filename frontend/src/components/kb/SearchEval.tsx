import { useState } from 'react'
import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { Search } from 'lucide-react'
import { cn } from 'cn'
import { Input } from '@/components/shadcn/input'
import { searchKB, type SearchHit, type SearchStats } from '../../api'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import EmptyState from '../common/EmptyState'
import HitCard, { type HitLocation } from '../trace/HitCard'
import { errorText } from '../../utils/errors'

// 检索评测：带 debug 统计的库内检索，看候选数 / 鉴权剔除 / 词法命中 / 分数分布与每条命中的向量 / 词法得分。
// 统计区是定义列表（4 列栅格），不是表格。
interface Props { kbId: number }

function Stat({ label, wide, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={cn('flex flex-col gap-0.5 bg-card px-3 py-2', wide && 'col-span-4')}>
      <dt className="text-[12.5px] text-muted-foreground">{label}</dt>
      <dd className="m-0 text-[13.5px]">{children}</dd>
    </div>
  )
}

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
    } catch (e) { toast.error(errorText(e, '检索失败')) } finally { setSearching(false) }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="输入检索内容，看命中片段与分数"
          className="min-w-[240px] flex-1"
          onKeyDown={(e) => { if (e.key === 'Enter') doSearch() }}
        />
        <span className="text-[12.5px] text-muted-foreground">Top K</span>
        <Input
          type="number"
          min={1}
          max={50}
          value={topK}
          onChange={(e) => setTopK(Number(e.target.value) || 1)}
          className="w-[80px]"
          aria-label="Top K"
        />
        <Button variant="primary" size="md" icon={<Search className="size-3.5" />} disabled={searching} onClick={doSearch}>
          {searching ? '检索中…' : '检索'}
        </Button>
      </div>

      {stats && (
        <dl className="m-0 grid grid-cols-4 gap-px overflow-hidden rounded-lg border border-border bg-border">
          <Stat label="关键词" wide>
            {stats.keywords?.length
              ? <span className="flex flex-wrap gap-1">{stats.keywords.map((k) => <Badge key={k} tone="info">{k}</Badge>)}</span>
              : '—'}
          </Stat>
          <Stat label="候选数">{stats.candidate_count}</Stat>
          <Stat label="返回数">{stats.returned}</Stat>
          <Stat label="鉴权剔除">
            <span className={stats.acl_rejected ? 'text-destructive' : undefined}>{stats.acl_rejected}</span>
          </Stat>
          <Stat label="词法命中">{stats.lexical_hit_count}</Stat>
          <Stat label="最高分"><span className="font-semibold text-primary">{stats.top_score}</span></Stat>
          <Stat label="平均分">{stats.mean_score}</Stat>
          <Stat label="重排">
            {stats.rerank_mode === 'model' ? <Badge tone="success">重排模型</Badge> : stats.rerank_mode === 'lexical' ? <Badge>词法（未配置或已降级）</Badge> : '—'}
          </Stat>
          <Stat label="耗时" wide>
            {stats.timings
              ? <span className="text-[12.5px] text-muted-foreground">向量化 {stats.timings.embed_ms ?? '-'} ms · 向量召回 {stats.timings.vector_ms ?? '-'} ms · 关键词召回 {stats.timings.keyword_ms ?? '-'} ms（{stats.timings.keyword_count ?? 0} 个词）· 重排 {stats.timings.rerank_ms ?? '-'} ms</span>
              : '—'}
          </Stat>
        </dl>
      )}

      {searched && results.length === 0 ? (
        <EmptyState description={stats?.kb_denied ? '当前角色无权检索这个知识库：按知识库当前的访问权限判定，调用者用绑定它的智能体对话时同样拿不到引用' : '没有命中片段：可能是文档尚未就绪、权限过滤剔除了全部候选，或检索词与文档内容差距较大'} />
      ) : (
        <div className="flex flex-col gap-2">
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
