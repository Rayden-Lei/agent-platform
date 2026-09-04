// 助手回答的 Markdown 渲染组件：把正文里的 [n] 引用标记转换成可悬浮查看来源详情的角标链接
import { useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Popover, Tag } from 'antd'
import type { Citation } from './types'

// 匹配回答里的引用标记 [1]、[2]、[1, 2]，但不匹配 markdown 链接 [text](url)。
// 仅当存在 citations 时才开启转换，避免无来源时误改正文。
const CITE_PATTERN = /(?<!\])\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g

// 把正文里的 [1]、[1, 2] 等引用标记替换为 citation:// 协议链接，交给下方 a 渲染分支转成角标
function toCitationLinks(content: string): string {
  return content.replace(CITE_PATTERN, (_match, nums: string) => {
    const idx = nums.replace(/\s+/g, '')
    return '[' + nums + '](citation://' + idx + ')'
  })
}

// 引用角标的悬浮卡片：展示来源文档名、相关度得分与内容片段（超长截断）
function CitationPopover({ citation, index }: { citation?: Citation; index: number }) {
  const text = citation?.content ? String(citation.content) : ''
  const clipped = text.length > 240 ? text.slice(0, 240) + '…' : text
  return (
    <div style={{ maxWidth: 320 }}>
      <div style={{ marginBottom: 6, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{citation?.doc_name || '来源 ' + index}</span>
        {typeof citation?.score === 'number' && (
          <Tag color="blue" style={{ marginInlineEnd: 0 }}>相关度 {citation.score.toFixed(2)}</Tag>
        )}
      </div>
      <div style={{ fontSize: 12.5, color: '#334155', lineHeight: 1.7 }}>{clipped || '无内容'}</div>
    </div>
  )
}

// 一组引用角标：按编号从 1 开始取 citations 中对应来源，逐个包上 Popover
function CitationMark({ indices, citations }: { indices: number[]; citations: Citation[] }) {
  return (
    <>
      {indices.map((idx) => {
        const citation = citations[idx - 1]
        return (
          <Popover
            key={idx}
            trigger="hover"
            placement="top"
            content={<CitationPopover citation={citation} index={idx} />}
          >
            <sup className="citation-mark">{idx}</sup>
          </Popover>
        )
      })}
    </>
  )
}

// 主组件：仅在存在 citations 时把 [n] 转成引用链接，避免污染无来源的正文；
// 通过 react-markdown 渲染 GFM 语法，并自定义 a 渲染器拦截 citation:// 链接
export default function AnswerMarkdown({ content, citations }: { content: string; citations?: Citation[] }) {
  const hasCitations = Array.isArray(citations) && citations.length > 0
  const transformed = useMemo(() => {
    if (!hasCitations) return content
    return toCitationLinks(content)
  }, [content, hasCitations])

  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) {
            // 拦截 citation:// 链接：拆出编号列表渲染成引用角标；普通链接照常新窗口打开
            if (typeof href === 'string' && href.startsWith('citation://')) {
              const indices = href
                .slice('citation://'.length)
                .split(',')
                .map((n) => parseInt(n, 10))
                .filter((n) => !Number.isNaN(n))
              return <CitationMark indices={indices} citations={citations || []} />
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {transformed}
      </ReactMarkdown>
    </div>
  )
}
