import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import {
  createMcpServer, parseMcpConfig, testMcpServer, updateMcpServer,
  type McpServerInput, type McpServerRow, type McpTestResult, type McpTransport,
} from '../../api'
import { errorText } from '../../utils/errors'

// MCP 服务器新增 / 编辑。
// 界面上要说清四件事（docs/17 §5）：
//   1. 只支持 HTTP / SSE —— 不接 stdio，那等于在服务器上执行配置里写的任意命令；
//   2. 凭据走这里加密存，不要写进请求头（写进去会被后端 400 拒掉，因为请求头会原样回传）；
//   3. allowed_hosts 必填 —— 地址是外部输入，没写白名单就无从判断目标是否可信；
//   4. 同步出来的工具默认停用，要人工逐个启用。
interface Props {
  open: boolean
  editing: McpServerRow | null
  onClose: () => void
  onSaved: () => void
}

interface FormValues {
  name: string
  description: string
  transport: McpTransport
  url: string
  secret: string
  clear_secret: boolean
  is_enabled: boolean
  /** 多行文本框里一行一个域名，提交时切数组 */
  allowed_hosts: string
  /** 请求头用 JSON 文本编辑：字段名不定，做不成固定表单；空字符串表示不带额外头 */
  headers: string
}

const EMPTY: FormValues = {
  name: '', description: '', transport: 'http', url: '', secret: '', clear_secret: false,
  is_enabled: true, allowed_hosts: '', headers: '',
}

const NAME_MAX = 64
const URL_MAX = 512

// 请求头是 JSON 对象：解析失败要给可读提示，而不是让后端 422
const parseHeaders = (text: string): { ok: true; value: Record<string, string> } | { ok: false; error: string } => {
  const t = text.trim()
  if (!t) return { ok: true, value: {} }
  try {
    const parsed = JSON.parse(t)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      return { ok: false, error: '请求头必须是 JSON 对象，如 {"X-Tenant": "acme"}' }
    }
    return { ok: true, value: Object.fromEntries(Object.entries(parsed).map(([k, v]) => [k, String(v)])) }
  } catch {
    return { ok: false, error: '请求头不是合法 JSON' }
  }
}

// 白名单：一行一个域名，允许逗号分隔；去掉协议、端口、路径这类写错的东西时给出提示而不是静默截断
const parseHosts = (text: string): { hosts: string[]; bad: string[] } => {
  const raw = text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean)
  const hosts: string[] = []
  const bad: string[] = []
  for (const h of raw) {
    if (h.includes('/') || h.includes(':') || h.length > 255) bad.push(h)
    else hosts.push(h.toLowerCase())
  }
  return { hosts, bad }
}

export default function McpServerForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<McpTestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  // 粘贴识别：new 时默认展开，editing 时收起（编辑不需要重新粘）
  const [pasteText, setPasteText] = useState('')
  const [pasteOpen, setPasteOpen] = useState(false)
  const [parsing, setParsing] = useState(false)
  const [pasteNotes, setPasteNotes] = useState<string[]>([])

  useEffect(() => {
    if (!open) return
    setError(null)
    setTestResult(null)
    setPasteText('')
    setPasteNotes([])
    // 新增时默认把粘贴框摆在最前面：多数人手上有现成配置，让他先粘比让他先填五个字段快
    setPasteOpen(!editing)
    if (editing) {
      setValues({
        name: editing.name, description: editing.description || '', transport: editing.transport,
        url: editing.url, secret: '', clear_secret: false, is_enabled: editing.is_enabled,
        allowed_hosts: (editing.allowed_hosts || []).join('\n'),
        headers: Object.keys(editing.headers || {}).length ? JSON.stringify(editing.headers, null, 2) : '',
      })
    } else {
      setValues(EMPTY)
    }
  }, [open, editing])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  const buildPayload = (v: FormValues): { payload?: McpServerInput; error?: string } => {
    if (!v.name.trim()) return { error: '请填写名称' }
    if (!v.url.trim()) return { error: '请填写服务器地址' }
    if (!/^https?:\/\//i.test(v.url.trim())) return { error: '地址必须以 http:// 或 https:// 开头（不支持 stdio）' }
    const { hosts, bad } = parseHosts(v.allowed_hosts)
    if (bad.length) return { error: `白名单只写域名，不要带协议、端口或路径：${bad.join(', ')}` }
    if (!hosts.length) return { error: '请填写 allowed_hosts：地址是外部输入，没有白名单就无从判断目标是否可信' }
    const headers = parseHeaders(v.headers)
    if (headers.ok === false) return { error: headers.error }
    const payload: McpServerInput = {
      name: v.name.trim(), description: v.description.trim() || null, transport: v.transport,
      url: v.url.trim(), headers: headers.value, is_enabled: v.is_enabled, allowed_hosts: hosts,
    }
    // 凭据三态：填了就是更换，勾了 clear_secret 就是清除，都没动则不传（后端沿用已存的）
    if (v.secret) payload.secret = v.secret
    else if (v.clear_secret) payload.clear_secret = true
    return { payload }
  }

  const onSubmit = async () => {
    const { payload, error: invalid } = buildPayload(values)
    if (!payload) { setError(invalid || '请检查表单'); return }
    setSubmitting(true)
    try {
      if (editing) await updateMcpServer(editing.id, payload)
      else await createMcpServer(payload)
      toast.success(editing ? '保存成功' : '创建成功')
      onSaved()
      onClose()
    } catch (e) {
      // 409 重名 / 400 校验失败：把后端 detail 原样上屏
      setError(errorText(e, '保存失败'))
    } finally {
      setSubmitting(false)
    }
  }

  // 粘贴识别：把一段配置拆成表单字段。识别不出的字段留空，由使用者补 —— 不猜。
  // 识别成功后填进表单，仍然要走「测试连接 / 保存」，不存在绕过校验的第二条路径
  const onParse = async () => {
    if (!pasteText.trim()) { setError('先粘贴一段配置'); return }
    setParsing(true)
    setError(null)
    setPasteNotes([])
    try {
      const parsed = await parseMcpConfig(pasteText)
      setValues((v) => ({
        ...v,
        name: parsed.name || v.name,
        url: parsed.url || v.url,
        transport: parsed.transport || v.transport,
        allowed_hosts: parsed.allowed_hosts.length ? parsed.allowed_hosts.join('\n') : v.allowed_hosts,
        headers: Object.keys(parsed.headers).length ? JSON.stringify(parsed.headers, null, 2) : v.headers,
        secret: parsed.secret || v.secret,
      }))
      setPasteNotes(parsed.notes)
      setPasteOpen(false)
      toast.success('已识别，确认下面的字段后点「测试连接」')
    } catch (e) {
      // 400 带原因（stdio 不支持 / 认不出结构），原样上屏比"识别失败"有用
      setError(errorText(e, '识别失败'))
    } finally {
      setParsing(false)
    }
  }

  // 测试连接不落库：新建时还没保存也能测；编辑时若没重填凭据，后端按 server_id 找回已存的
  const onTest = async () => {
    const { payload, error: invalid } = buildPayload(values)
    if (!payload) { setError(invalid || '请检查表单'); return }
    setTesting(true)
    setError(null)
    setTestResult(null)
    try {
      const result = await testMcpServer({ ...payload, server_id: editing?.id })
      setTestResult(result)
      toast.success(`连接成功，远端有 ${result.count} 个工具`)
    } catch (e) {
      setError(errorText(e, '连接失败'))
    } finally {
      setTesting(false)
    }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={760}
      title={editing ? `编辑 MCP 服务器：${editing.name}` : '新增 MCP 服务器'}
      error={error}
      footer={
        <>
          {/* 两个按钮互斥：都在读同一份表单状态，而保存会改 is_enabled / 凭据三态，
              测试连接时保存、或保存时测试，都会拿半新半旧的配置去发请求 */}
          <Button variant="ghost" size="md" disabled={submitting || testing} onClick={onClose}>取消</Button>
          <Button variant="secondary" size="md" disabled={submitting || testing} onClick={onTest}>{testing ? '连接中…' : '测试连接'}</Button>
          <Button variant="primary" size="md" disabled={submitting || testing} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        {/* 粘贴识别：放在最前面。多数人手上有现成配置，先粘一次就能填好大半字段 */}
        <div className="rounded-lg border border-border bg-[var(--bg-soft)] px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[13px] font-medium">从现有配置粘贴（可选）</div>
              <div className="mt-0.5 text-[12px] text-muted-foreground">
                支持：服务器地址 · Claude/Cursor 的 <code className="font-mono">mcpServers</code> JSON · 「地址 + 凭据」两行
              </div>
            </div>
            {!pasteOpen && (
              <Button variant="secondary" size="sm" onClick={() => setPasteOpen(true)}>粘贴识别</Button>
            )}
          </div>
          {pasteOpen && (
            <div className="mt-2 flex flex-col gap-2">
              <textarea
                rows={4}
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder={'https://mcp.example.com/mcp\n\n或整段粘贴：\n{\n  "mcpServers": {\n    "github": { "url": "https://…/mcp", "headers": { "Authorization": "Bearer xxx" } }\n  }\n}'}
                className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-[12.5px] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
              />
              <div className="flex items-center gap-2">
                <Button variant="primary" size="sm" disabled={parsing} onClick={onParse}>
                  {parsing ? '识别中…' : '识别并填入'}
                </Button>
                <Button variant="ghost" size="sm" onClick={() => { setPasteOpen(false); setPasteText(''); setPasteNotes([]) }}>收起</Button>
                <span className="text-[12px] text-muted-foreground">识别不落库，填完仍要「测试连接」确认</span>
              </div>
            </div>
          )}
          {pasteNotes.length > 0 && (
            <ul className="mt-2 flex list-disc flex-col gap-0.5 pl-4 text-[12px] text-muted-foreground">
              {pasteNotes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </div>

        <div className="flex flex-col gap-3 sm:flex-row">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="mcp-name">名称</Label>
            <Input id="mcp-name" value={values.name} maxLength={NAME_MAX} onChange={(e) => set('name', e.target.value)} placeholder="例如：内部知识检索" />
            <p className="m-0 text-[12px] text-muted-foreground">同步出来的工具名会以它为前缀（如 <code className="font-mono">内部知识检索_search</code>），避免跨服务器重名</p>
          </div>
          <div className="flex flex-col gap-1.5 sm:w-[180px]">
            <Label htmlFor="mcp-transport">传输</Label>
            <Select value={values.transport} onValueChange={(v) => set('transport', v as McpTransport)}>
              <SelectTrigger id="mcp-transport" className="h-9 text-[13px]"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="http">HTTP（推荐）</SelectItem>
                <SelectItem value="sse">SSE（旧版）</SelectItem>
              </SelectContent>
            </Select>
            <p className="m-0 text-[12px] text-muted-foreground">不支持 stdio</p>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mcp-url">服务器地址</Label>
          <Input
            id="mcp-url"
            value={values.url}
            maxLength={URL_MAX}
            onChange={(e) => set('url', e.target.value)}
            placeholder="https://mcp.example.com/mcp"
            className="font-mono text-[13px]"
          />
          <p className="m-0 text-[12px] text-muted-foreground">
            只支持 HTTP / SSE。不接 stdio —— 那等于在服务器上执行这里写的任意命令
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mcp-hosts">目标地址白名单（必填）</Label>
          <textarea
            id="mcp-hosts"
            rows={2}
            value={values.allowed_hosts}
            onChange={(e) => set('allowed_hosts', e.target.value)}
            placeholder={'mcp.example.com\nv2.mcp.example.com'}
            className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-[13px] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <p className="m-0 text-[12px] text-muted-foreground">
            一行一个域名，只写主机名（不带协议、端口、路径）。子域名要单独列：<code className="font-mono">api.example.com</code> 覆盖不了 <code className="font-mono">x.api.example.com</code>
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mcp-secret">
            凭据（可选）{editing?.has_secret && <span className="ml-1 font-normal text-muted-foreground">· 已配置</span>}
          </Label>
          <Input
            id="mcp-secret"
            type="password"
            value={values.secret}
            onChange={(e) => set('secret', e.target.value)}
            placeholder={editing?.has_secret ? '留空表示沿用已有凭据' : '以 Bearer Token 发送'}
            autoComplete="new-password"
            className="font-mono text-[13px]"
          />
          {editing?.has_secret && (
            <label className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
              <input type="checkbox" checked={values.clear_secret} onChange={(e) => set('clear_secret', e.target.checked)} />
              清除已保存的凭据
            </label>
          )}
          <p className="m-0 text-[12px] text-muted-foreground">
            加密保存，任何接口都不会回传明文。凭据要填在这里，不要写进下面的请求头 —— 请求头会原样回传
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mcp-headers">额外请求头（可选，JSON 对象）</Label>
          <textarea
            id="mcp-headers"
            rows={3}
            value={values.headers}
            onChange={(e) => set('headers', e.target.value)}
            placeholder={'{\n  "X-Tenant": "acme"\n}'}
            className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-[13px] outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
          <p className="m-0 text-[12px] text-muted-foreground">
            只放非敏感头。含 authorization / token / key / secret 这类字样的键会被拒绝，凭据请填在上面
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="mcp-desc">描述（可选）</Label>
          <textarea
            id="mcp-desc"
            rows={2}
            value={values.description}
            onChange={(e) => set('description', e.target.value)}
            placeholder="这个服务器提供哪类能力"
            className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 text-[13px] leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
          />
        </div>

        <label className="flex items-start gap-2 rounded-lg border border-border px-3 py-2.5">
          <input type="checkbox" className="mt-0.5" checked={values.is_enabled} onChange={(e) => set('is_enabled', e.target.checked)} />
          <span className="text-[13px]">
            启用
            <span className="mt-0.5 block text-[12px] text-muted-foreground">停用会同时停用它同步出来的全部工具（地址与凭据都在服务器这一行上）</span>
          </span>
        </label>

        {testResult && (
          <div className="rounded-lg border border-border px-3 py-2.5 text-[12.5px]">
            <span className="text-[var(--success)]">连接成功</span>
            <span className="text-muted-foreground">，远端有 {testResult.count} 个工具</span>
            {testResult.tools.length > 0 && (
              <div className="mt-1 flex flex-wrap gap-1">
                {testResult.tools.slice(0, 20).map((t) => (
                  <code key={t} className="rounded bg-[var(--bg-soft)] px-1.5 py-0.5 text-[11.5px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>{t}</code>
                ))}
                {testResult.tools.length > 20 && <span className="text-[12px] text-muted-foreground">等 {testResult.tools.length} 个</span>}
              </div>
            )}
          </div>
        )}

        <p className="m-0 text-[12px] text-muted-foreground">
          保存后在列表里点「同步」拉取远端工具。新同步出来的工具默认停用 —— 远端工具的描述是外部输入，先看过再启用。
        </p>


      </div>
    </Drawer>
  )
}
