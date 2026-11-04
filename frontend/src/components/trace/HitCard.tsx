import { useState } from 'react'
import { cn } from 'cn'
import Badge from '../ui/Badge'
import Button from '../ui/Button'

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
  const [expanded, setExpanded] = useState(false)
  const where = locationText(location)
  const long = !!content && (content.split('\n').length > 3 || content.length > 240)

  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
        <Badge tone="info">#{rank}</Badge>
        <span className="text-[13.5px] font-medium text-foreground">{docName || '文档 ' + (docId ?? '?')}</span>
        {where && <span className="text-[12px] text-muted-foreground">{where}</span>}
        <span className="text-[12px] text-muted-foreground">score {score.toFixed(4)}</span>
      </div>
      <div className="flex flex-col gap-2 px-3 py-2.5">
        {content && (
          <div>
            <p className={cn('m-0 whitespace-pre-wrap text-[13.5px] leading-relaxed text-foreground', !expanded && 'line-clamp-3')}>{content}</p>
            {long && (
              <Button size="sm" variant="ghost" className="mt-1" onClick={() => setExpanded(!expanded)}>{expanded ? '收起' : '展开'}</Button>
            )}
          </div>
        )}
        {typeof vectorScore === 'number' && (
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge>向量 {vectorScore}</Badge>
            <Badge>词法 {keywordScore}</Badge>
            {typeof rerankScore === 'number' && <Badge tone="success">重排 {rerankScore.toFixed(4)}</Badge>}
            {(matchedKeywords || []).map((k) => <Badge key={k} tone="info">{k}</Badge>)}
          </div>
        )}
      </div>
    </section>
  )
}
