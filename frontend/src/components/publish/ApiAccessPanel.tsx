import { useState } from 'react'
import { ChevronDown, Copy } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/shadcn/alert'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/shadcn/tabs'
import { copyText } from '../../utils/clipboard'
import Button from '../ui/Button'
import { BODY_ROWS, ERROR_ROWS, EVENT_ROWS, KEY_PLACEHOLDER, curlSnippet, endpointRows, jsSnippet, markdownDoc, pythonSnippet, type DocRow } from './apiSnippets'

// 智能体"发布渠道 → API 调用"（docs/15 3.7.2，PB-02）：Base URL、智能体 ID、鉴权方式、端点与请求体、SSE 事件、错误码、
// curl / Python / JS 流式示例与"复制对接说明"（Markdown，Key 用占位符）。数据由页面传入，本组件不发请求。
interface Props {
  agent: { id: number; name: string; status: string }
  baseUrl: string            // 对外地址（PUBLIC_BASE_URL，未配置时是当前访问地址）
  baseUrlConfigured: boolean
}

// 行内代码 + 复制：原来 antd 的 Typography.Text copyable
function CodeText({ children, copy }: { children: string; copy?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <code className="select-all break-all rounded bg-secondary px-1.5 py-0.5 font-mono text-[12.5px] text-foreground">{children}</code>
      {copy && (
        <Button size="sm" variant="ghost" aria-label="复制" onClick={() => copyText(children, '')}><Copy className="size-3.5" /></Button>
      )}
    </span>
  )
}

// 代码块 + 右上角复制；深色底用语义 token（bg-foreground / text-background），不写死色值
function Snippet({ code, label }: { code: string; label: string }) {
  return (
    <div className="relative">
      <div className="absolute right-2 top-2">
        <Button size="sm" variant="secondary" icon={<Copy className="size-3.5" />} onClick={() => copyText(code, label)}>复制</Button>
      </div>
      <pre className="m-0 max-h-[360px] overflow-auto rounded-lg bg-foreground px-3.5 py-3 pr-20 font-mono text-[12px] leading-relaxed text-background">{code}</pre>
    </div>
  )
}

// 两列文档表（端点 / 字段 / 事件 / 错误码），固定几行，用原生 table
function DocTable({ rows, first }: { rows: DocRow[]; first: string }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <table className="w-full border-collapse text-[13.5px]">
        <thead className="bg-secondary">
          <tr>
            <th className="w-[260px] px-3 py-2 text-left text-[12.5px] font-medium text-muted-foreground">{first}</th>
            <th className="px-3 py-2 text-left text-[12.5px] font-medium text-muted-foreground">说明</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border align-top">
              <td className="px-3 py-2"><code className="break-all font-mono text-[12.5px] text-foreground">{r.name}</code></td>
              <td className="px-3 py-2 text-muted-foreground">{r.desc}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// 折叠段落：原来 antd Collapse，展开状态自己管（shadcn 没有 accordion 组件）
function Disclosure({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="overflow-hidden rounded-lg border border-border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-[13px] font-medium text-foreground hover:bg-accent"
      >
        {title}
        <ChevronDown className={`size-4 shrink-0 text-muted-foreground transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
      </button>
      {open && <div className="border-t border-border p-2">{children}</div>}
    </div>
  )
}

export default function ApiAccessPanel({ agent, baseUrl, baseUrlConfigured }: Props) {
  const api = `${baseUrl}/api/v1`
  const published = agent.status === 'published'
  return (
    <section className="flex flex-col rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">API 调用</h3>
        <Button icon={<Copy className="size-3.5" />} onClick={() => copyText(markdownDoc(api, agent), '对接说明（Markdown）')}>复制对接说明</Button>
      </div>

      <div className="flex flex-col gap-3 p-3.5">
        {!published && (
          <Alert className="border-border-strong">
            <AlertTitle>{agent.status === 'offline' ? '已下线：按示例调用会返回 403「智能体已下线」，重新发布后恢复' : '发布后才能调用：现在按示例调用会返回 403「智能体未发布」'}</AlertTitle>
          </Alert>
        )}

        <Alert className="border-border-strong">
          <AlertDescription>API Key 只在服务端调用，不要放进浏览器、小程序或 App；Key 只能调用授权给它的智能体（下方密钥区）</AlertDescription>
        </Alert>

        <dl className="m-0 grid grid-cols-1 gap-y-2 rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center gap-2">
            <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">Base URL</dt>
            <dd className="m-0 flex min-w-0 flex-wrap items-center gap-2 text-[13px]">
              <CodeText copy>{api}</CodeText>
              {!baseUrlConfigured && <span className="text-[12px] text-muted-foreground">（未配置 PUBLIC_BASE_URL，这是你当前访问的地址）</span>}
            </dd>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">智能体 ID</dt>
            <dd className="m-0 min-w-0 text-[13px]"><CodeText copy>{String(agent.id)}</CodeText></dd>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <dt className="w-[88px] shrink-0 text-[12.5px] text-muted-foreground">鉴权</dt>
            <dd className="m-0 min-w-0 text-[13px]"><CodeText>{`Authorization: Bearer ${KEY_PLACEHOLDER}`}</CodeText></dd>
          </div>
        </dl>

        <Tabs defaultValue="curl">
          <TabsList>
            <TabsTrigger value="curl">curl</TabsTrigger>
            <TabsTrigger value="python">Python</TabsTrigger>
            <TabsTrigger value="js">JavaScript</TabsTrigger>
          </TabsList>
          <TabsContent value="curl"><Snippet code={curlSnippet(api, agent.id)} label=" curl 示例" /></TabsContent>
          <TabsContent value="python"><Snippet code={pythonSnippet(api, agent.id)} label=" Python 示例" /></TabsContent>
          <TabsContent value="js"><Snippet code={jsSnippet(api, agent.id)} label=" JavaScript 示例" /></TabsContent>
        </Tabs>

        <div className="flex flex-col gap-2">
          <Disclosure title="端点"><DocTable rows={endpointRows(agent.id)} first="端点" /></Disclosure>
          <Disclosure title="对话请求体（end_user、client_message_id 幂等）"><DocTable rows={BODY_ROWS} first="字段" /></Disclosure>
          <Disclosure title="返回：SSE 事件"><DocTable rows={EVENT_ROWS} first="type" /></Disclosure>
          <Disclosure title="错误码"><DocTable rows={ERROR_ROWS} first="状态码" /></Disclosure>
        </div>
      </div>
    </section>
  )
}
