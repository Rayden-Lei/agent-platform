import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Checkbox } from '@/components/shadcn/checkbox'
import { Input } from '@/components/shadcn/input'
import { Label } from '@/components/shadcn/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/shadcn/select'
import { Textarea } from '@/components/shadcn/textarea'
import Drawer from '../ui/Drawer'
import Button from '../ui/Button'
import { createTool, updateTool, type ToolAuthType, type ToolConfig, type ToolConfigField, type ToolInput, type ToolRow } from '../../api'
import { statusOptions } from '../../constants/status'
import ToolParamsEditor, { rowsFromSchema, schemaFromRows, type ParamRow } from './ToolParamsEditor'
import { errorText } from '../../utils/errors'

// 工具新增 / 编辑：HTTP 工具的方法 / 地址 / 请求头结构化录入，参数声明用表格；builtin 类型 config 恒为空对象。
// 凭据走"鉴权"区（docs/15 RS-06）：加密托管、保存后任何地方都不回显；编辑时留空表示沿用，勾选"清除"才删除。
// 字段多、HTTP 工具还要展开一整段请求配置 → 用抽屉（整高、正文滚动、按钮常驻），不用弹窗。
interface Props { open: boolean; editing: ToolRow | null; onClose: () => void; onSaved: () => void }
interface FormValues {
  name: string; description: string; type: 'builtin' | 'http'; timeout: number; method: string; url: string; headersStr: string; params: ParamRow[]
  allowedHosts: string
  authType: ToolAuthType; authLocation: 'header' | 'query'; authName: string; secret: string; clearSecret: boolean
  // 内置工具自己的配置（config_fields 声明的那些）。secret 类的值不进这里——
  // 它走上面统一的 secret/clearSecret 通道，加密后存 tools.secret_enc
  configValues: Record<string, string | number>
}
const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const AUTH_TYPES = [
  { value: 'none', label: '不需要' }, { value: 'bearer', label: 'Bearer Token（Authorization 头）' },
  { value: 'api_key', label: 'API Key（自定义请求头或查询参数）' }, { value: 'basic', label: 'Basic（用户名:密码）' },
]
const EMPTY: FormValues = {
  name: '', description: '', type: 'builtin', timeout: 30, method: 'POST', url: '', headersStr: '', params: [], allowedHosts: '',
  authType: 'none', authLocation: 'header', authName: '', secret: '', clearSecret: false,
  configValues: {},
}

export default function ToolForm({ open, editing, onClose, onSaved }: Props) {
  const [values, setValues] = useState<FormValues>(EMPTY)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const hasSecret = !!editing?.auth?.has_secret
  // 内置工具自己的配置项声明（后端下发）。有声明才渲染配置区，HTTP 工具与无配置的内置工具都没有
  const fields = (editing?.config?.config_fields || []) as ToolConfigField[]
  const hasBuiltinSecret = fields.some((f) => f.kind === 'secret')

  useEffect(() => {
    if (!open) return
    setError(null)
    if (!editing) { setValues(EMPTY); return }
    const { parameters, url, method, headers, allowed_hosts, config_fields, ...restConfig } = editing.config || {}
    // 内置工具的配置项：按声明取值（声明里的 default 兜底）；secret 类不取当前值（读不回来）
    const configValues: Record<string, string | number> = {}
    for (const f of config_fields || []) {
      if (f.kind === 'secret') continue
      const raw = (restConfig as Record<string, unknown>)[f.key]
      configValues[f.key] = raw === undefined || raw === null || raw === '' ? (f.default as string | number) : (raw as string | number)
    }
    setValues({
      // MCP 工具不会进这个表单（列表里只给「去连接器」入口，后端 update_tool 也拒），
      // 这里收窄成 'http' 只是为了让类型成立，不会真的写回 mcp
      name: editing.name, description: editing.description,
      type: editing.type === 'mcp' ? 'http' : editing.type, timeout: editing.timeout, method: (method || 'POST').toUpperCase(),
      url: url ?? '', headersStr: headers && Object.keys(headers).length ? JSON.stringify(headers, null, 2) : '',
      params: rowsFromSchema(parameters), allowedHosts: (allowed_hosts || []).join('\n'),
      // 内置工具的凭据单独管理（存 secret_enc），不占"鉴权"区，否则会被当成 HTTP 工具的鉴权配置
      authType: (config_fields || []).some((f) => f.kind === 'secret') ? 'none' : (editing.auth?.type ?? 'none'),
      authLocation: editing.auth?.location === 'query' ? 'query' : 'header',
      authName: editing.auth?.name ?? '', secret: '', clearSecret: false,
      configValues,
    })
  }, [open, editing])

  const set = <K extends keyof FormValues>(key: K, v: FormValues[K]) => setValues((s) => ({ ...s, [key]: v }))

  // 服务端同样会校验，这里只是提前给出可读提示
  const validate = (v: FormValues): string | null => {
    if (!v.name.trim()) return '请填写名称'
    if (!v.description.trim()) return '请填写描述'
    if (v.type !== 'http') return null
    if (!v.url.trim()) return '请输入请求地址'
    if (!/^https?:\/\/\S+$/i.test(v.url.trim())) return '请输入合法的 URL'
    if (!v.allowedHosts.trim()) return 'HTTP 工具必须填写目标地址白名单'
    if (v.authType === 'api_key' && !v.authName.trim()) return '请填写参数名'
    if (v.authType !== 'none' && !hasSecret && !v.secret.trim()) return '请填写凭据'
    return null
  }

  const onSubmit = async () => {
    const invalid = validate(values)
    if (invalid) { setError(invalid); return }
    let config: ToolConfig = {}
    if (values.type === 'http') {
      let headers: Record<string, string> = {}
      if (values.headersStr?.trim()) {
        try { headers = JSON.parse(values.headersStr) } catch { setError('请求头 JSON 格式错误'); return }
        if (typeof headers !== 'object' || Array.isArray(headers)) { setError('请求头必须是 JSON 对象'); return }
      }
      // 保留 config 里前端不认识的键（后端扩展字段），只覆盖结构化录入的几项
      const { parameters: _p, url: _u, method: _m, headers: _h, allowed_hosts: _a, ...rest } = editing?.config || {}
      // 白名单每行一个主机名（也接受逗号）。清空时删掉这个键而不是写空数组：接口上两者都表示"不限制"，
      // 但缺失更干净，也避免以后收紧语义时把"用户明确清空"和"从没配过"混成同一种状态（docs/16 P3a 过渡期）
      const hosts = (values.allowedHosts || '').split(/[\n,]/).map((h) => h.trim()).filter(Boolean)
      config = { ...rest, method: values.method, url: values.url, headers, parameters: schemaFromRows(values.params || []), ...(hosts.length ? { allowed_hosts: hosts } : {}) }
    }
    if (values.type === 'builtin' && fields.length) {
      // 内置工具的配置写回 config：只覆盖声明里列出的键，保留后端其它字段；
      // 数字项转成数字（后端按 int 处理），文本项去空白
      const prev = { ...(editing?.config || {}) } as Record<string, unknown>
      delete prev.config_fields
      delete prev.parameters
      for (const f of fields) {
        if (f.kind === 'secret') continue
        const raw = values.configValues[f.key]
        if (f.kind === 'int') {
          const n = Number(raw)
          prev[f.key] = Number.isFinite(n) ? n : f.min
        } else {
          prev[f.key] = String(raw ?? '').trim()
        }
      }
      config = prev as ToolConfig
    }
    const authType = values.type === 'http' ? values.authType : 'none'
    const auth = authType === 'api_key' ? { type: authType, location: values.authLocation, name: values.authName } : { type: authType }
    // 内置工具的密钥（如 web_search 的 API Key）也存 secret_enc，但不经"鉴权"区：
    // auth 恒为 none，secret 只在该工具有 secret 类配置项时才发送
    const builtinSecret = hasBuiltinSecret && values.secret ? { secret: values.secret } : {}
    const payload: ToolInput = {
      name: values.name, description: values.description, type: values.type, config, timeout: values.timeout, auth,
      ...(authType !== 'none' && values.secret ? { secret: values.secret } : {}),
      ...builtinSecret,
      clear_secret: hasBuiltinSecret ? !!values.clearSecret : (authType === 'none' || !!values.clearSecret),
    }
    setSubmitting(true)
    try {
      if (editing) await updateTool(editing.id, payload)
      else await createTool(payload)
      toast.success(editing ? '保存成功' : '创建成功')
      onSaved()
      onClose()
    } catch (e) { setError(errorText(e, '保存失败')) } finally { setSubmitting(false) }
  }

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={720}
      title={editing ? `编辑工具：${editing.name}` : '新增工具'}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={onClose}>取消</Button>
          <Button variant="primary" size="md" disabled={submitting} onClick={onSubmit}>{submitting ? '保存中…' : '保存'}</Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tool-name">名称</Label>
          <Input id="tool-name" value={values.name} onChange={(e) => set('name', e.target.value)} placeholder="例如：weather_query" />
          <p className="m-0 text-[12px] text-muted-foreground">模型按名称选择工具，用英文标识更稳定</p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="tool-desc">描述</Label>
          <Textarea id="tool-desc" rows={2} value={values.description} onChange={(e) => set('description', e.target.value)} placeholder="模型据此判断何时调用，写清用途与输入输出" className="resize-y text-[13px]" />
        </div>

        <div className="flex gap-3">
          <div className="flex flex-1 flex-col gap-1.5">
            <Label htmlFor="tool-type">类型</Label>
            <Select value={values.type} disabled={!!editing} onValueChange={(v) => set('type', v as 'builtin' | 'http')}>
              <SelectTrigger id="tool-type" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>
                {statusOptions('toolType').map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          <div className="flex w-[130px] flex-col gap-1.5">
            <Label htmlFor="tool-timeout">超时（秒）</Label>
            <Input id="tool-timeout" type="number" min={1} max={300} value={values.timeout} onChange={(e) => set('timeout', Number(e.target.value))} />
          </div>
        </div>

{values.type === 'builtin' && fields.length > 0 && (
  <div className="flex flex-col gap-3 rounded-lg border border-border px-3 py-3">
    <div className="flex flex-col gap-0.5">
      <Label>工具配置</Label>
      <p className="m-0 text-[12px] text-muted-foreground">这些是{values.name || '该工具'}自己的配置，保存后下一次调用即生效</p>
    </div>
    {fields.map((f) => {
      const isSecretField = f.kind === 'secret'
      const cur = values.configValues[f.key]
      return (
        <div key={f.key} className="flex flex-col gap-1.5">
          <Label htmlFor={`tool-cfg-${f.key}`} className="text-[12.5px]">{f.label}</Label>
          {isSecretField ? (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                id={`tool-cfg-${f.key}`}
                type="password"
                value={values.secret}
                onChange={(e) => set('secret', e.target.value)}
                placeholder={hasSecret ? '已配置（留空则保持，输入新值则覆盖）' : (f.placeholder || '未配置')}
                className="h-9 w-full max-w-[420px]"
              />
              {hasSecret && (
                <label className="flex items-center gap-1.5 text-[12.5px] text-muted-foreground">
                  <Checkbox checked={values.clearSecret} onCheckedChange={(v) => set('clearSecret', !!v)} />
                  清除已配置的密钥
                </label>
              )}
            </div>
          ) : f.kind === 'int' ? (
            <div className="flex items-center gap-2">
              <Input
                id={`tool-cfg-${f.key}`} type="number" min={f.min} max={f.max} step={f.step}
                value={String(cur ?? f.default)}
                onChange={(e) => set('configValues', { ...values.configValues, [f.key]: e.target.value === '' ? f.default : Number(e.target.value) })}
                className="h-9 w-[140px]"
              />
              {f.unit && <span className="text-[12.5px] text-muted-foreground">{f.unit}</span>}
              <span className="text-[12px] text-muted-foreground">范围 {f.min}～{f.max}，默认 {f.default}</span>
            </div>
          ) : (
            <Input
              id={`tool-cfg-${f.key}`}
              value={String(cur ?? '')}
              onChange={(e) => set('configValues', { ...values.configValues, [f.key]: e.target.value })}
              placeholder={f.placeholder || String(f.default ?? '')}
              className="h-9 w-full max-w-[460px]"
            />
          )}
          <p className="m-0 text-[12px] leading-relaxed text-muted-foreground">{f.description}</p>
        </div>
      )
    })}
  </div>
)}
        {values.type === 'http' && (
          <>
            <div className="flex gap-3">
              <div className="flex w-[120px] flex-col gap-1.5">
                <Label htmlFor="tool-method">方法</Label>
                <Select value={values.method} onValueChange={(v) => set('method', v)}>
                  <SelectTrigger id="tool-method" className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {METHODS.map((m) => <SelectItem key={m} value={m}>{m}</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="tool-url">请求地址</Label>
                <Input id="tool-url" value={values.url} onChange={(e) => set('url', e.target.value)} placeholder="https://api.example.com/v1/query" />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tool-hosts">目标地址白名单</Label>
              <Textarea id="tool-hosts" rows={3} value={values.allowedHosts} onChange={(e) => set('allowedHosts', e.target.value)} placeholder={'api.example.com\nv2.example.com'} className="resize-y font-mono text-[13px]" />
              <p className="m-0 text-[12px] text-muted-foreground">每行一个主机名（如 api.example.com），子域自动放行。不填的 HTTP 工具在对话与工作流里会被直接拒绝（2026-10-26 起），只有工具页的测试调用能跑（docs/16 P3a）</p>
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="tool-headers">请求头（JSON 对象，可选）</Label>
              <Textarea id="tool-headers" rows={3} value={values.headersStr} onChange={(e) => set('headersStr', e.target.value)} placeholder='{"Content-Type": "application/json"}' className="resize-y font-mono text-[13px]" />
              <p className="m-0 text-[12px] text-muted-foreground">只放非敏感的请求头；Authorization、Token、Key 这类凭据在下方鉴权里配置（写进这里保存会被拒绝）</p>
            </div>

            <ToolAuthFields
              values={values}
              set={set}
              hasSecret={hasSecret}
            />

            <div className="flex flex-col gap-1.5">
              <Label>参数声明（模型按此以结构化参数调用）</Label>
              <ToolParamsEditor value={values.params} onChange={(rows) => set('params', rows)} />
            </div>
          </>
        )}

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </div>
    </Drawer>
  )
}

// 鉴权区：api_key 要选位置与参数名；凭据用密码框，已配置时留空表示沿用（服务端同样校验：选了方式却没有凭据 400）
function ToolAuthFields({ values, set, hasSecret }: {
  values: FormValues
  set: <K extends keyof FormValues>(key: K, v: FormValues[K]) => void
  hasSecret: boolean
}) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border px-3 py-3">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="tool-auth-type">鉴权</Label>
        <Select value={values.authType} onValueChange={(v) => set('authType', v as ToolAuthType)}>
          <SelectTrigger id="tool-auth-type" className="w-full"><SelectValue /></SelectTrigger>
          <SelectContent>
            {AUTH_TYPES.map((o) => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>

      {values.authType !== 'none' && (
        <>
          {values.authType === 'api_key' && (
            <div className="flex gap-3">
              <div className="flex w-[140px] flex-col gap-1.5">
                <Label htmlFor="tool-auth-location">位置</Label>
                <Select value={values.authLocation} onValueChange={(v) => set('authLocation', v as 'header' | 'query')}>
                  <SelectTrigger id="tool-auth-location" className="w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="header">请求头</SelectItem>
                    <SelectItem value="query">查询参数</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-1 flex-col gap-1.5">
                <Label htmlFor="tool-auth-name">参数名</Label>
                <Input id="tool-auth-name" value={values.authName} onChange={(e) => set('authName', e.target.value)} placeholder="X-API-Key" />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tool-secret">凭据</Label>
            <Input
              id="tool-secret"
              type="password"
              autoComplete="new-password"
              value={values.secret}
              onChange={(e) => set('secret', e.target.value)}
              placeholder={hasSecret ? '已配置，留空不修改' : values.authType === 'basic' ? '用户名:密码' : '粘贴 Token / Key'}
            />
            <p className="m-0 text-[12px] text-muted-foreground">加密保存，之后任何页面与接口都不回显；调用时按上面的方式带上</p>
          </div>

          {hasSecret && (
            <div className="flex items-center gap-2">
              <Checkbox id="tool-clear-secret" checked={values.clearSecret} onCheckedChange={(v) => set('clearSecret', v === true)} />
              <Label htmlFor="tool-clear-secret" className="text-[13px] font-normal">清除已保存的凭据</Label>
            </div>
          )}
        </>
      )}
    </div>
  )
}
