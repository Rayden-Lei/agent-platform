import { useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import TimeCell from '../common/TimeCell'
import { testTool, type McpServerDetail, type McpToolRow } from '../../api'
import { errorText } from '../../utils/errors'

// MCP 服务器详情：看到它同步出来的工具清单，以及每个工具被几个智能体引用。
//
// 这里可以直接启用 / 停用工具（2026-11-08 起）。原先只读、要求去工具页操作，理由是
// "两处都能改会让当前状态含糊"；实际上工具页混着十几种来源的工具、还要翻页找，
// 而使用者此刻的意图就是"我刚同步完，把要用的打开" —— 让他跳走再回来是纯粹的摩擦。
// 两处读的是同一份 is_enabled，不存在状态歧义。
interface Props {
  server: McpServerDetail | null
  onClose: () => void
  onEdit: (server: McpServerDetail) => void
  onSync: (server: McpServerDetail) => void
  /** 同步 + 一键启用（新建服务器后的标准动作） */
  onSyncAndEnable: (server: McpServerDetail) => void
  onToggleTool: (toolId: number) => void
  /** 一键启用 / 停用该服务器名下全部工具 */
  onBulkToggle: (enabled: boolean) => void
  syncing: boolean
  bulkRunning: boolean
}

export default function McpServerDrawer({
  server, onClose, onEdit, onSync, onSyncAndEnable, onToggleTool, onBulkToggle, syncing, bulkRunning,
}: Props) {
  if (!server) return null
  const copyUrl = async () => {
    try {
      await navigator.clipboard.writeText(server.url)
      toast.success('已复制地址')
    } catch {
      toast.error('复制失败，请手动选中')
    }
  }
  const tools = server.tools ?? []
  const enabledCount = tools.filter((t) => t.is_enabled).length

  return (
    <Drawer
      open={!!server}
      onClose={onClose}
      width={760}
      title={server.name}
      description={`${server.transport === 'sse' ? 'SSE' : 'HTTP'} · ${tools.length} 个工具（启用 ${enabledCount} 个）`}
      extra={
        <span className="inline-flex items-center gap-1.5">
          <Button size="sm" variant="primary" disabled={!server.is_enabled || syncing} onClick={() => onSyncAndEnable(server)}>
            {syncing ? '同步中…' : '同步并全部启用'}
          </Button>
          <Button size="sm" variant="secondary" disabled={!server.is_enabled || syncing} onClick={() => onSync(server)}>
            仅同步
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onEdit(server)}>编辑</Button>
        </span>
      }
      footer={<Button variant="primary" size="md" onClick={onClose}>关闭</Button>}
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={server.is_enabled ? 'success' : 'neutral'}>{server.is_enabled ? '已启用' : '已停用'}</Badge>
          {server.has_secret && <Badge tone="info">已配置凭据</Badge>}
          {server.last_error && <Badge tone="danger" title={server.last_error}>上次同步失败</Badge>}
          {server.last_synced_at && <Badge tone="neutral">上次同步 <TimeCell value={server.last_synced_at} /></Badge>}
        </div>

        <div className="flex flex-col gap-2 rounded-lg border border-border px-3 py-2.5">
          <Field label="地址">
            <span className="inline-flex min-w-0 items-center gap-1.5">
              <code className="truncate" style={{ fontFamily: '"SF Mono",Consolas,monospace', fontSize: 12 }}>{server.url}</code>
              <button type="button" onClick={copyUrl} className="rounded p-0.5 text-muted-foreground hover:bg-accent" aria-label="复制地址">
                <span className="text-[11px]">复制</span>
              </button>
            </span>
          </Field>
          <Field label="白名单">
            {server.allowed_hosts?.length
              ? <span className="inline-flex flex-wrap gap-1">{server.allowed_hosts.map((h) => <code key={h} className="rounded bg-[var(--bg-soft)] px-1.5 py-0.5 text-[11.5px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>{h}</code>)}</span>
              : <span className="text-muted-foreground">未配置</span>}
          </Field>
          <Field label="描述">{server.description || '-'}</Field>
          <Field label="创建人">{server.created_by_username || (server.created_by ? '#' + server.created_by : '-')}</Field>
          <Field label="创建时间"><TimeCell value={server.created_at} /></Field>
        </div>

        {server.last_error && (
          <div className="rounded-lg border border-border px-3 py-2.5">
            <span className="text-[12px] font-medium text-destructive">上次同步失败原因</span>
            <pre className="m-0 mt-1 whitespace-pre-wrap break-words text-[12px] leading-relaxed text-muted-foreground" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
              {server.last_error}
            </pre>
          </div>
        )}

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[12px] font-medium text-muted-foreground">
              同步出的工具（{tools.length}，启用 {enabledCount}）
            </span>
            {tools.length > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <Button size="sm" variant="secondary" disabled={bulkRunning || enabledCount === tools.length}
                  onClick={() => onBulkToggle(true)}>
                  {bulkRunning ? '处理中…' : '全部启用'}
                </Button>
                <Button size="sm" variant="ghost" disabled={bulkRunning || enabledCount === 0}
                  onClick={() => onBulkToggle(false)}>
                  全部停用
                </Button>
              </span>
            )}
          </div>
          {tools.length === 0 ? (
            <p className="m-0 rounded-lg border border-dashed border-border px-3 py-4 text-center text-[12.5px] text-muted-foreground">
              还没有同步过。点右上「同步并全部启用」一步拉取远端清单并打开全部工具；
              想先逐个看过再启用就点「仅同步」，新工具会以停用状态进来。
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-1 rounded-lg border border-border p-1.5">
              {tools.map((t) => (
                <McpToolItem key={t.id} tool={t} onToggle={() => onToggleTool(t.id)} />
              ))}
            </ul>
          )}
          <p className="m-0 text-[12px] text-muted-foreground">
            新同步的工具默认停用：远端工具的描述是外部输入，先看过再启用。远端已删除的工具会标成停用并保留，不会破坏已绑定它的智能体。
          </p>
        </div>
      </div>
    </Drawer>
  )
}

// 详情里的一行「标签 : 值」，标签定宽保证多行对齐（与技能抽屉同一写法）
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 text-[13px]">
      <span className="w-[56px] shrink-0 text-[12px]" style={{ color: 'var(--fg-muted)' }}>{label}</span>
      <span className="min-w-0 flex-1 break-words">{children}</span>
    </div>
  )
}

// 单个同步工具：名字 + 状态开关 + 「试用」展开。
//
// 试用放在这里而不是让使用者跳去工具页：工具页混着内置 / HTTP / MCP 十几种来源、还要翻页找，
// 而此刻的意图就是"我刚同步完，试试这个工具通不通"。用真实参数调一次是唯一能确认
// "远端真的能用"的办法 —— 同步成功只说明 list_tools 通了，不代表 tools/call 通。
function McpToolItem({ tool, onToggle }: { tool: McpToolRow; onToggle: () => void }) {
  const [open, setOpen] = useState(false)
  const [args, setArgs] = useState<Record<string, string>>({})
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<string | null>(null)

  const props = Object.entries(tool.parameters?.properties || {})
  const required = new Set(tool.parameters?.required || [])

  const run = async () => {
    setRunning(true)
    setResult(null)
    try {
      // 空值不传：让后端按"未提供"处理，而不是收到空字符串（布尔/数字会因此校验失败）
      const payload: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(args)) {
        if (v === '' || v === undefined) continue
        // 数字类参数要转成数字，否则后端参数校验会拒（模型那边由 schema 约束，这里是人工输入）
        const declared = tool.parameters?.properties?.[k]?.type
        payload[k] = declared === 'integer' || declared === 'number' ? Number(v) : v
      }
      const res = await testTool(tool.id, { args: payload })
      const data = (res as { data?: { result?: unknown } })?.data?.result
      setResult(typeof data === 'string' ? data : JSON.stringify(data, null, 2))
    } catch (e) {
      setResult('❌ ' + errorText(e, '调用失败'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <li className="flex flex-col gap-1 px-1 py-0.5">
      <div className="flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate text-[12.5px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }} title={tool.name}>
          {tool.name}
        </code>
        {tool.source_missing && <Badge tone="danger">远端已移除</Badge>}
        <span className="shrink-0 text-[11.5px] text-muted-foreground" title="远端原始工具名">{tool.remote_name}</span>
        <span className="w-[68px] shrink-0 text-right text-[11.5px] text-muted-foreground" title="引用该工具的智能体数">
          {tool.agents_count ? `${tool.agents_count} 个智能体` : '未绑定'}
        </span>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="shrink-0 rounded px-1.5 py-0.5 text-[11.5px] text-muted-foreground hover:bg-accent"
        >
          {open ? '收起' : '试用'}
        </button>
        <button
          type="button"
          role="switch"
          aria-checked={tool.is_enabled}
          aria-label={`${tool.is_enabled ? '停用' : '启用'} ${tool.name}`}
          onClick={onToggle}
          className={`shrink-0 rounded-full px-2 py-0.5 text-[11.5px] transition-colors ${tool.is_enabled
            ? 'bg-[var(--success-bg,rgba(16,185,129,0.12))] text-[var(--success)]'
            : 'bg-[var(--bg-soft)] text-muted-foreground'}`}
        >
          {tool.is_enabled ? '已启用' : '已停用'}
        </button>
      </div>

      {open && (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-[var(--bg-soft)] px-2.5 py-2">
          {tool.description && <p className="m-0 text-[12px] text-muted-foreground">{tool.description}</p>}
          {tool.schema_notes.length > 0 && (
            <ul className="m-0 flex list-disc flex-col gap-0.5 pl-4 text-[11.5px] text-muted-foreground">
              {tool.schema_notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
          {props.length === 0 ? (
            <p className="m-0 text-[12px] text-muted-foreground">该工具没有参数，直接点「调用」。</p>
          ) : (
            props.map(([name, prop]) => (
              <div key={name} className="flex flex-col gap-1">
                <Label className="text-[11.5px]">
                  {name}{required.has(name) && <span className="ml-0.5 text-destructive">*</span>}
                  <span className="ml-1 font-normal text-muted-foreground">{prop.type}{prop.enum ? ' · 可选 ' + prop.enum.join(' / ') : ''}</span>
                </Label>
                <Input
                  value={args[name] ?? ''}
                  onChange={(e) => setArgs((a) => ({ ...a, [name]: e.target.value }))}
                  placeholder={prop.description || name}
                  className="h-7 text-[12px]"
                />
              </div>
            ))
          )}
          <div className="flex items-center gap-2">
            <Button size="sm" variant="primary" disabled={running || !tool.is_enabled} onClick={run}>
              {running ? '调用中…' : '调用'}
            </Button>
            {!tool.is_enabled && <span className="text-[11.5px] text-muted-foreground">先启用才能试用</span>}
          </div>
          {result !== null && (
            <pre className="m-0 max-h-[200px] overflow-auto whitespace-pre-wrap break-words rounded bg-background px-2 py-1 text-[11.5px] leading-relaxed" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
              {result}
            </pre>
          )}
        </div>
      )}
    </li>
  )
}

