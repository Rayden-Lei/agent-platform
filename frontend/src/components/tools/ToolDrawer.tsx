import type { ReactNode } from 'react'
import { toast } from 'sonner'
import { cn } from 'cn'
import { Copy, FlaskConical } from 'lucide-react'
import { getTool, type ToolProperty, type ToolRow } from '../../api'
import { useAsyncData } from '../../hooks/useAsyncData'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import ErrorState from '../common/ErrorState'
import ResourceLink from '../common/ResourceLink'
import StatusTag from '../common/StatusTag'
import TimeCell from '../common/TimeCell'
import { TYPE_OPTIONS } from './ToolParamsEditor'

// 工具详情抽屉：请求配置、鉴权（只显示方式与是否已配置，凭据不回显）、参数声明表、绑定它的智能体；测试 / 编辑在头部。
// 请求头里已不允许放凭据（保存时 422），所以直接显示值
interface Props { tool: ToolRow | null; canManage: boolean; onClose: () => void; onTest: (tool: ToolRow) => void; onEdit: (tool: ToolRow) => void }

const AUTH_LABEL: Record<string, string> = { bearer: 'Bearer Token', api_key: 'API Key', basic: 'Basic' }
function authText(tool: ToolRow) {
  const auth = tool.auth
  if (!auth || auth.type === 'none') return <span className="text-muted-foreground">不需要</span>
  const where = auth.type === 'api_key' ? `（${auth.location === 'query' ? '查询参数' : '请求头'} ${auth.name}）` : ''
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      {AUTH_LABEL[auth.type] ?? auth.type}{where}
      {auth.has_secret ? <Badge tone="success">凭据已配置</Badge> : <Badge tone="danger">缺少凭据</Badge>}
    </span>
  )
}

// 详情字段：dl 里的两列定义列表，wide 占满一行（描述、请求这类长内容）
function Cell({ label, wide, children }: { label: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={cn('flex flex-col gap-0.5 bg-card px-3 py-2', wide && 'col-span-2')}>
      <dt className="text-[12px] text-muted-foreground">{label}</dt>
      <dd className="m-0 text-[13px]">{children}</dd>
    </div>
  )
}

export default function ToolDrawer({ tool, canManage, onClose, onTest, onEdit }: Props) {
  const id = tool?.id ?? 0
  const detail = useAsyncData(() => getTool(id), [id], { auto: !!tool, errorText: '加载工具详情失败' })
  const params = tool?.config?.parameters
  const rows = Object.entries(params?.properties || {}).map(([name, p]: [string, ToolProperty]) => ({ name, ...p, required: (params?.required || []).includes(name) }))
  const headerNames = Object.keys(tool?.config?.headers || {})
  const copyUrl = (url: string) => navigator.clipboard?.writeText(url).then(() => toast.success('已复制'))

  return (
    <Drawer
      open={!!tool}
      title={tool ? `工具：${tool.name}` : ''}
      onClose={onClose}
      width={720}
      extra={tool && (
        <>
          <Button icon={<FlaskConical className="size-3.5" />} onClick={() => onTest(tool)}>测试</Button>
          <Button variant="primary" disabled={!canManage} onClick={() => onEdit(tool)}>编辑</Button>
        </>
      )}
    >
      {tool && (
        <div className="flex flex-col gap-4">
          <dl className="m-0 grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-2">
            <Cell label="类型"><StatusTag domain="toolType" value={tool.type} /></Cell>
            <Cell label="状态"><StatusTag domain="enabled" value={tool.is_enabled} /></Cell>
            <Cell label="描述" wide>{tool.description}</Cell>
            {tool.type === 'http' && (
              <>
                <Cell label="请求" wide>
                  <span className="flex items-center gap-1.5">
                    <Badge tone="info">{(tool.config?.method || 'POST').toUpperCase()}</Badge>
                    <code className="min-w-0 break-all text-[12.5px]">{tool.config?.url || '-'}</code>
                    {tool.config?.url && (
                      <Button size="sm" variant="ghost" aria-label="复制请求地址" onClick={() => copyUrl(tool.config.url)}>
                        <Copy className="size-3.5" />
                      </Button>
                    )}
                  </span>
                </Cell>
                <Cell label="请求头" wide>
                  {headerNames.length ? (
                    <span className="flex flex-wrap gap-1">
                      {headerNames.map((h) => <Badge key={h}>{h}: {tool.config?.headers?.[h]}</Badge>)}
                    </span>
                  ) : <span className="text-muted-foreground">无</span>}
                </Cell>
                <Cell label="鉴权" wide>{authText(tool)}</Cell>
              </>
            )}
            <Cell label="超时">{`${tool.timeout} 秒`}</Cell>
            <Cell label="绑定智能体">{tool.agents_count}</Cell>
            <Cell label="创建人">{tool.created_by_username || '-'}</Cell>
            <Cell label="更新时间"><TimeCell value={tool.updated_at} /></Cell>
          </dl>

          {tool.type === 'http' && (
            <div className="flex flex-col gap-2">
              <span className="text-[13px] font-medium">参数声明（{rows.length}）</span>
              {rows.length ? (
                <div className="overflow-hidden rounded-lg border border-border">
                  <table className="w-full border-collapse text-[13px]">
                    <thead className="bg-secondary">
                      <tr>
                        <th className="w-[160px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">参数</th>
                        <th className="w-[90px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">类型</th>
                        <th className="px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">说明</th>
                        <th className="w-[200px] px-2 py-1.5 text-left text-[12px] font-medium text-muted-foreground">枚举</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.name} className="border-t border-border">
                          <td className="px-2 py-1.5">{r.name}{r.required && <span className="text-destructive"> *</span>}</td>
                          <td className="px-2 py-1.5">{TYPE_OPTIONS.find((o) => o.value === r.type)?.label ?? r.type}</td>
                          <td className="px-2 py-1.5">{r.description || '-'}</td>
                          <td className="px-2 py-1.5">
                            {r.enum?.length
                              ? <span className="flex flex-wrap gap-1">{r.enum.map((x) => <Badge key={x}>{x}</Badge>)}</span>
                              : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div><Badge tone="warning">未声明参数：模型只能以空参数调用，建议补充声明</Badge></div>
              )}
            </div>
          )}

          <div className="flex flex-col gap-2">
            <span className="text-[13px] font-medium">绑定它的智能体（{tool.agents_count}）</span>
            {detail.error ? <ErrorState compact message={detail.error} onRetry={() => detail.reload()} /> : detail.data?.agents.length ? (
              <div className="flex flex-col gap-1.5">
                {detail.data.agents.map((a) => (
                  <span key={a.id} className="flex items-center gap-1.5">
                    <ResourceLink type="agent" id={a.id} name={a.name} showIcon /> <StatusTag domain="agent" value={a.status} />
                  </span>
                ))}
              </div>
            ) : <span className="text-[13px] text-muted-foreground">{detail.loading ? '加载中…' : '没有智能体绑定该工具'}</span>}
          </div>

          {!tool.is_enabled && <div><Badge tone="warning">已停用：智能体对话不会带上该工具，工作流工具节点会直接失败</Badge></div>}
        </div>
      )}
    </Drawer>
  )
}
