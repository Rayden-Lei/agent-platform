import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { listLlmCalls, type LlmCallRow } from '../../api'
import { errorText } from '../../utils/errors'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import TimeCell from '../common/TimeCell'

// 运行详情里的「模型调用」页签：把这次运行的每次上游请求列出来。
//
// 与调用链（trace step）的分工：调用链是"平台视角"（这一步做了什么、多久），
// 这里是"上游视角"（实际收到什么、回了什么）。排查"模型为什么这么答"只能靠后者。
// 放在运行详情里而不是只能去日志页搜：排查时是"这次运行出问题了"，
// 顺着运行看报文最直接；日志页适合跨运行检索（哪个地址失败了、这个模型最近返回了什么）。
interface Props {
  runId: number
}

export default function RunLlmCalls({ runId }: Props) {
  const [rows, setRows] = useState<LlmCallRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  useEffect(() => {
    let alive = true
    setLoading(true)
    listLlmCalls({ run_id: runId, page_size: 100 })
      .then((page) => { if (alive) { setRows(page.items); setError(null) } })
      .catch((e) => { if (alive) { setRows([]); setError(errorText(e, '加载模型调用失败')) } })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [runId])

  const toggle = (id: number) => setExpanded((s) => {
    const next = new Set(s)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  if (loading) return <p className="m-0 py-6 text-center text-[13px] text-muted-foreground">加载中…</p>
  if (error) return <p className="m-0 py-6 text-center text-[13px] text-destructive">{error}</p>
  if (!rows.length) {
    return (
      <p className="m-0 rounded-lg border border-dashed border-border px-3 py-6 text-center text-[13px] text-muted-foreground">
        这次运行没有模型调用记录。若确实应该有时，检查 LLM_LOG_ENABLED 是否被关掉了。
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="m-0 text-[12.5px] text-muted-foreground">
        共 {rows.length} 次上游调用。点「展开」看完整请求体与响应原文（凭据已打码，其余原样）。
      </p>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
        {rows.map((r) => (
          <li key={r.id} className="rounded-lg border border-border px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={r.status === 'success' ? 'success' : 'danger'}>
                {r.status === 'success' ? '成功' : '失败'}
              </Badge>
              <span className="text-[12.5px] font-medium">{r.model_name || '-'}</span>
              <span className="text-[11.5px] text-muted-foreground">{r.purpose}</span>
              <span className="text-[11.5px] tabular-nums text-muted-foreground">
                {r.prompt_tokens} / {r.completion_tokens} token · {(r.duration_ms / 1000).toFixed(1)}s
              </span>
              {r.called_tools.length > 0 && (
                <span className="text-[11.5px] text-muted-foreground">调了 {r.called_tools.filter(Boolean).length} 个工具</span>
              )}
              <span className="ml-auto text-[11.5px] text-muted-foreground"><TimeCell value={r.started_at} /></span>
              <Button size="sm" variant="ghost" onClick={() => toggle(r.id)}>
                {expanded.has(r.id) ? '收起' : '展开'}
              </Button>
            </div>
            <div className="mt-1">
              <code className="block truncate text-[11.5px] text-muted-foreground" style={{ fontFamily: '"SF Mono",Consolas,monospace' }} title={r.url}>
                {r.url}
              </code>
            </div>
            {expanded.has(r.id) && <CallBody callId={r.id} />}
          </li>
        ))}
      </ul>
    </div>
  )
}

// 展开后才去取完整报文：列表接口故意不带大字段（上百条几 MB 会让页面卡死）
function CallBody({ callId }: { callId: number }) {
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof import('../../api').getLlmCall>> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    import('../../api').then(({ getLlmCall }) => getLlmCall(callId))
      .then((d) => { if (alive) setDetail(d) })
      .catch((e) => { if (alive) setError(errorText(e, '加载报文失败')) })
    return () => { alive = false }
  }, [callId])

  if (error) return <p className="m-0 mt-1 text-[12px] text-destructive">{error}</p>
  if (!detail) return <p className="m-0 mt-1 text-[12px] text-muted-foreground">加载报文…</p>

  const messages = ((detail.request_body?.messages as { role?: string; content?: unknown }[] | undefined) || [])
  return (
    <div className="mt-2 flex flex-col gap-2">
      {detail.error && (
        <pre className="m-0 whitespace-pre-wrap break-words rounded bg-[var(--bg-soft)] px-2 py-1 text-[11.5px] text-destructive" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
          {detail.error}
        </pre>
      )}
      {detail.reasoning_text && <Block title={`思考过程（${detail.reasoning_text.length} 字）`} text={detail.reasoning_text} />}
      {detail.response_text && <Block title={`回答正文（${detail.response_text.length} 字）`} text={detail.response_text} />}
      {messages.length > 0 && (
        <div className="flex flex-col gap-1">
          <span className="text-[11.5px] font-medium text-muted-foreground">请求消息（{messages.length} 条）</span>
          {messages.map((m, i) => (
            <div key={i} className="rounded border border-border px-2 py-1">
              <span className="text-[11px] text-muted-foreground">{m.role || '-'}</span>
              <pre className="m-0 max-h-[180px] overflow-auto whitespace-pre-wrap break-words text-[11.5px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
                {typeof m.content === 'string' ? m.content : JSON.stringify(m.content, null, 2)}
              </pre>
            </div>
          ))}
        </div>
      )}
      {detail.tools_offered.length > 0 && (
        <span className="text-[11.5px] text-muted-foreground">
          发给模型的工具：{detail.tools_offered.map((t) => t.name).join('、')}
        </span>
      )}
      {detail.tool_calls.length > 0 && <Block title={`模型调用（${detail.tool_calls.length} 次）`} text={JSON.stringify(detail.tool_calls, null, 2)} />}
      {detail.request_body && <Block title="请求体原文" text={JSON.stringify(detail.request_body, null, 2)} />}
      {detail.response_body && <Block title={`响应原文（${detail.response_body.length} 字符）`} text={detail.response_body} />}
    </div>
  )
}

function Block({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11.5px] font-medium text-muted-foreground">{title}</span>
      <pre className="m-0 max-h-[320px] overflow-auto whitespace-pre-wrap break-words rounded bg-[var(--bg-soft)] px-2 py-1 text-[11.5px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
        {text}
      </pre>
    </div>
  )
}
