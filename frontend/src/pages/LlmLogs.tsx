import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Cpu } from 'lucide-react'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import {
  getLlmCall, getLlmCallStats, listLlmCalls,
  type LlmCallDetail, type LlmCallRow, type LlmCallStats,
} from '../api'
import { usePagedList } from '../hooks/usePagedList'
import { useQueryState } from '../hooks/useQueryState'
import ListPage from '../components/layout/ListPage'
import PageHeader from '../components/layout/PageHeader'
import FilterBar from '../components/layout/FilterBar'
import SearchInput from '../components/common/SearchInput'
import EmptyState from '../components/common/EmptyState'
import DataTable from '../components/table/DataTable'
import Drawer from '../components/ui/Drawer'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import TimeCell from '../components/common/TimeCell'
import type { DataColumn } from '../components/table/DataTable'
import { errorText } from '../utils/errors'

type Filters = { q?: string; status?: string; purpose?: string }
const DEFAULTS: Filters = { q: undefined, status: undefined, purpose: undefined }

const PURPOSE_LABEL: Record<string, string> = {
  chat: '对话', workflow: '工作流', debug: '调试', summary: '摘要',
  rewrite: '检索改写', probe: '连通测试', embedding: '向量化',
}

// 模型调用日志：每次请求的**完整报文**。
// 为什么需要它：调用链只记"回答多少字、用了哪些工具"，排查"模型为什么这么答"
// "为什么没调工具""上游到底返回了什么"时全都看不到 —— 只有原始报文能回答。
// 打码口径：只有凭据打码，地址、请求体、响应体、错误原文全部原样保留。
export default function LlmLogs() {
  const [filters, setFilters, resetFilters] = useQueryState(DEFAULTS)
  const [stats, setStats] = useState<LlmCallStats | null>(null)
  const [current, setCurrent] = useState<LlmCallDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const empty = <EmptyState description="还没有模型调用记录。发起一次对话或测试一次模型连通性后，这里会记录完整的请求与响应报文。" />
  const list = usePagedList<LlmCallRow>(listLlmCalls, { filters, emptyText: empty })

  useEffect(() => { getLlmCallStats().then(setStats).catch(() => setStats(null)) }, [])

  const open = async (r: LlmCallRow) => {
    setLoadingDetail(true)
    try { setCurrent(await getLlmCall(r.id)) } catch (e) { toast.error(errorText(e, '加载详情失败')) } finally { setLoadingDetail(false) }
  }

  const columns = useMemo<DataColumn<LlmCallRow>[]>(() => [
    {
      key: 'started_at', header: '时间', width: 150, sortable: true,
      cell: (r) => <TimeCell value={r.started_at} />,
    },
    {
      key: 'model_name', header: '模型 / 用途', width: 190,
      cell: (r) => (
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-[13px]" title={r.model_name}>{r.model_name || '-'}</span>
          <span className="text-[11.5px] text-muted-foreground">{PURPOSE_LABEL[r.purpose] || r.purpose}</span>
        </div>
      ),
    },
    {
      key: 'url', header: '地址',
      cell: (r) => (
        <code className="block truncate text-[12px] text-muted-foreground" style={{ fontFamily: '"SF Mono",Consolas,monospace' }} title={r.url}>
          {r.url || '-'}
        </code>
      ),
    },
    {
      key: 'tools', header: '工具', width: 120,
      cell: (r) => {
        const called = r.called_tools.filter(Boolean)
        if (!called.length) return <span className="text-[12px] text-muted-foreground">{r.tool_names.length ? `给了 ${r.tool_names.length} 个` : '无'}</span>
        return <span className="text-[12px]" title={called.join('、')}>调了 {called.length} 个</span>
      },
    },
    {
      key: 'tokens', header: 'Token', width: 110,
      cell: (r) => <span className="text-[12px] tabular-nums text-muted-foreground">{r.prompt_tokens} / {r.completion_tokens}</span>,
    },
    {
      key: 'duration_ms', header: '耗时', width: 110, sortable: true,
      cell: (r) => (
        <span className="text-[12px] tabular-nums text-muted-foreground">
          {(r.duration_ms / 1000).toFixed(1)}s{r.first_token_ms != null && <span className="ml-1 opacity-70">首 {r.first_token_ms}ms</span>}
        </span>
      ),
    },
    {
      key: 'status', header: '状态', width: 100,
      cell: (r) => (
        <span className="inline-flex items-center gap-1">
          <Badge tone={r.status === 'success' ? 'success' : 'danger'}>{r.status === 'success' ? (r.http_status || 'OK') : (r.http_status || '失败')}</Badge>
          {r.truncated && <Badge tone="neutral">已截断</Badge>}
        </span>
      ),
    },
    {
      key: 'op', header: '', width: 70, align: 'right', pinRight: true,
      cell: (r) => <Button size="sm" variant="ghost" onClick={() => open(r)}>详情</Button>,
    },
  ], [])

  return (
    <ListPage
      header={
        <PageHeader
          icon={<Cpu />}
          title="模型调用日志"
          description="每次模型调用的完整报文：请求地址、messages 全文、工具定义、响应原文、思考过程、用量与耗时。凭据已打码，其余原样保存。"
          extra={stats && (
            <span className="text-[12.5px] text-muted-foreground">
              共 {stats.total} 次 · 今日 {stats.today} 次{stats.failed > 0 && <span className="ml-1 text-destructive">失败 {stats.failed}</span>}
              {!stats.enabled && <span className="ml-2 text-destructive">日志已关闭（LLM_LOG_ENABLED=false）</span>}
            </span>
          )}
        />
      }
      filters={
        <FilterBar onReset={resetFilters} onRefresh={list.reload} loading={list.loading}
          activeCount={Object.values(filters).filter(Boolean).length}>
          <SearchInput value={filters.q} onChange={(q) => setFilters({ q })} placeholder="搜索地址 / 模型 / 错误" />
          <Select value={filters.status ?? 'all'} onValueChange={(v) => setFilters({ status: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[100px] text-[13px]" aria-label="状态"><SelectValue placeholder="状态" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部状态</SelectItem>
              <SelectItem value="success">成功</SelectItem>
              <SelectItem value="error">失败</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.purpose ?? 'all'} onValueChange={(v) => setFilters({ purpose: v === 'all' ? undefined : v })}>
            <SelectTrigger size="sm" className="h-8 w-[110px] text-[13px]" aria-label="用途"><SelectValue placeholder="用途" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部用途</SelectItem>
              {Object.entries(PURPOSE_LABEL).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
            </SelectContent>
          </Select>
        </FilterBar>
      }
    >
      <DataTable
        columns={columns}
        rows={list.items}
        rowKey={(r) => r.id}
        loading={list.loading || loadingDetail}
        error={list.error}
        empty={empty}
        onRetry={list.reload}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        onPageChange={list.load}
        sort={list.sort}
        onSortChange={list.setSort}
      />
      <CallDetailDrawer call={current} onClose={() => setCurrent(null)} />
    </ListPage>
  )
}

// 详情：四段 —— 概览、请求体、响应原文、工具。默认展开概览，报文折叠（可能几十 KB）
function CallDetailDrawer({ call, onClose }: { call: LlmCallDetail | null; onClose: () => void }) {
  if (!call) return null
  const messages = ((call.request_body?.messages as { role?: string; content?: unknown }[] | undefined) || [])
  return (
    <Drawer open={!!call} onClose={onClose} width={960}
      title={`调用 #${call.id} · ${call.model_name || '未知模型'}`}
      description={`${PURPOSE_LABEL[call.purpose] || call.purpose} · ${call.status === 'success' ? '成功' : '失败'} · ${(call.duration_ms / 1000).toFixed(2)}s`}
      footer={<Button variant="primary" size="md" onClick={onClose}>关闭</Button>}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={call.status === 'success' ? 'success' : 'danger'}>{call.status === 'success' ? '成功' : '失败'}</Badge>
          {call.http_status != null && <Badge tone="neutral">HTTP {call.http_status}</Badge>}
          <Badge tone="neutral">{call.prompt_tokens} 输入 / {call.completion_tokens} 输出 token</Badge>
          {call.first_token_ms != null && <Badge tone="neutral">首 token {call.first_token_ms}ms</Badge>}
          {call.run_id != null && <Badge tone="info">运行 #{call.run_id}</Badge>}
          {call.truncated && <Badge tone="danger">报文已截断</Badge>}
        </div>

        <Field label="地址">
          <code className="break-all text-[12px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>{call.url || '-'}</code>
        </Field>

        {call.error && (
          <div className="rounded-lg border border-border px-3 py-2">
            <span className="text-[12px] font-medium text-destructive">错误原文</span>
            <pre className="m-0 mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>{call.error}</pre>
          </div>
        )}

        {call.reasoning_text && (
          <Block title={`思考过程（${call.reasoning_text.length} 字）`} text={call.reasoning_text} />
        )}

        {call.response_text && (
          <Block title={`回答正文（${call.response_text.length} 字）`} text={call.response_text} defaultOpen />
        )}

        {messages.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">请求消息（{messages.length} 条，实际发给上游的内容）</span>
            <div className="flex flex-col gap-1.5">
              {messages.map((m, i) => (
                <div key={i} className="rounded-lg border border-border px-3 py-2">
                  <span className="text-[11.5px] font-medium text-muted-foreground">{m.role || '-'}</span>
                  <pre className="m-0 mt-1 max-h-[220px] overflow-auto whitespace-pre-wrap break-words text-[12px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
                    {typeof m.content === 'string' ? m.content : JSON.stringify(m.content, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </div>
        )}

        {call.tools_offered.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">发给模型的工具（{call.tools_offered.length} 个）</span>
            <ul className="m-0 flex list-none flex-col gap-1 rounded-lg border border-border p-1.5">
              {call.tools_offered.map((t) => (
                <li key={t.name} className="flex flex-col gap-0.5 px-1 py-0.5">
                  <code className="text-[12.5px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>{t.name}</code>
                  {t.description && <span className="text-[11.5px] text-muted-foreground">{t.description}</span>}
                </li>
              ))}
            </ul>
          </div>
        )}

        {call.tool_calls.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[12px] font-medium text-muted-foreground">模型实际调用（{call.tool_calls.length} 次）</span>
            <pre className="m-0 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border px-3 py-2 text-[12px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
              {JSON.stringify(call.tool_calls, null, 2)}
            </pre>
          </div>
        )}

        {call.request_body && <Block title="请求体原文（含全部参数）" text={JSON.stringify(call.request_body, null, 2)} />}
        {call.response_body && <Block title={`响应原文（${call.response_body.length} 字符，流式为 SSE 帧）`} text={call.response_body} />}
      </div>
    </Drawer>
  )
}

function Block({ title, text, defaultOpen = false }: { title: string; text: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="flex flex-col gap-1">
      <button type="button" onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 self-start text-[12px] font-medium text-muted-foreground hover:text-foreground">
        {open ? '▾' : '▸'} {title}
      </button>
      {open && (
        <pre className="m-0 max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg border border-border px-3 py-2 text-[12px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
          {text}
        </pre>
      )}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 text-[13px]">
      <span className="w-[56px] shrink-0 text-[12px]" style={{ color: 'var(--fg-muted)' }}>{label}</span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </div>
  )
}
