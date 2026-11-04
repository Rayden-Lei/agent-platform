import { Copy, ExternalLink, QrCode, RefreshCw } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/shadcn/alert'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/shadcn/popover'
import { Switch } from '@/components/shadcn/switch'
import { Skeleton } from '@/components/shadcn/skeleton'
import type { AgentShare, AgentShareInput } from '../../api'
import ErrorState from '../common/ErrorState'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import { copyText } from '../../utils/clipboard'
import ShareSettingsForm from './ShareSettingsForm'

// "发布渠道"第一张卡片：分享体验链接（docs/15 3.6，PB-01）。开关、链接（复制 / 二维码 / 新窗口预览 / 重置）、预检结果与访问设置。
// 链接按 PUBLIC_BASE_URL 拼（服务端给 share_url），没配置时用当前访问地址。数据与保存由页面（useAgentShare）注入，本组件不发请求。
interface Props {
  share: AgentShare | null
  error?: string | null
  saving: boolean
  onRetry: () => void
  onSave: (input: AgentShareInput, okText?: string) => Promise<boolean>
  onReset: () => Promise<void>
}

const configOf = (s: AgentShare): AgentShareInput => ({
  is_enabled: s.is_enabled, access_mode: s.access_mode, expires_at: s.expires_at, rate_limit_per_minute: s.rate_limit_per_minute,
  daily_message_limit: s.daily_message_limit, visitor_daily_limit: s.visitor_daily_limit, allow_http_tools: s.allow_http_tools, show_citations: s.show_citations,
})

export default function ShareLinkCard({ share, error, saving, onRetry, onSave, onReset }: Props) {
  if (error) {
    return (
      <section className="flex flex-col rounded-xl border border-border bg-card">
        <div className="border-b border-border px-3.5 py-2.5"><h3 className="m-0 text-[13px] font-semibold text-foreground">分享链接</h3></div>
        <div className="p-3"><ErrorState compact message={error} onRetry={onRetry} /></div>
      </section>
    )
  }
  if (!share) {
    return (
      <section className="flex flex-col rounded-xl border border-border bg-card">
        <div className="border-b border-border px-3.5 py-2.5"><h3 className="m-0 text-[13px] font-semibold text-foreground">分享链接</h3></div>
        <div className="flex flex-col gap-2 p-3.5">
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-4 w-1/2" />
          <Skeleton className="h-9 w-full" />
        </div>
      </section>
    )
  }

  const url = share.code ? share.share_url || `${window.location.origin}/s/${share.code}` : null
  const toggle = (checked: boolean) => onSave({ ...configOf(share), is_enabled: checked }, checked ? '分享已开启' : '分享已关闭：链接立即失效')

  return (
    <section className="flex flex-col rounded-xl border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3.5 py-2.5">
        <h3 className="m-0 text-[13px] font-semibold text-foreground">分享链接</h3>
        <div className="flex items-center gap-2">
          <span className="text-[12.5px] text-muted-foreground">{share.is_enabled ? '已开启' : '未开启'}</span>
          <Switch
            checked={share.is_enabled}
            disabled={saving || (!share.published && !share.is_enabled)}
            onCheckedChange={toggle}
            aria-label="开启分享"
          />
        </div>
      </div>

      <div className="flex flex-col gap-3 p-3.5">
        <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">
          生成一个体验链接，不登录平台也能和线上版本对话；访客只看到回答与引用，看不到提示词、模型、工具入参与运行记录。
        </p>

        {!share.published && (
          <Alert className="border-border-strong">
            <AlertTitle>智能体还没有发布：发布后才能开启分享</AlertTitle>
          </Alert>
        )}

        {url && (
          <div className="flex flex-col gap-2">
            {/* http 下剪贴板不可用：链接放在可手动全选的位置 */}
            <code className="select-all break-all rounded-lg border border-border bg-secondary px-2.5 py-2 font-mono text-[12.5px] leading-relaxed text-foreground">{url}</code>
            <div className="flex flex-wrap items-center gap-1.5">
              <Button size="sm" icon={<Copy className="size-3.5" />} onClick={() => copyText(url, '分享链接')}>复制</Button>
              <Popover>
                <PopoverTrigger asChild>
                  <Button size="sm" icon={<QrCode className="size-3.5" />}>二维码</Button>
                </PopoverTrigger>
                <PopoverContent align="start" className="w-[260px]">
                  <p className="m-0 mb-1.5 text-[12px] text-muted-foreground">手机上打开这个链接即可体验（可直接选中复制）</p>
                  <code className="block select-all break-all rounded-md bg-secondary px-2 py-1.5 font-mono text-[12px] leading-relaxed text-foreground">{url}</code>
                </PopoverContent>
              </Popover>
              <a
                href={url}
                target="_blank"
                rel="noopener noreferrer"
                aria-disabled={!share.is_enabled}
                onClick={(e) => { if (!share.is_enabled) e.preventDefault() }}
                className={`inline-flex h-7 items-center gap-1 rounded-lg border border-border-strong bg-card px-2.5 text-[12.5px] font-medium text-foreground hover:bg-accent ${share.is_enabled ? '' : 'pointer-events-none opacity-50'}`}
              >
                <ExternalLink className="size-3.5" aria-hidden="true" />
                新窗口预览
              </a>
              <InlineConfirm message="换一个新地址，旧链接与已打开页面的访客立即失效" confirmLabel="重置" onConfirm={() => { void onReset() }}>
                <Button size="sm" variant="danger" icon={<RefreshCw className="size-3.5" />}>重置链接</Button>
              </InlineConfirm>
            </div>
          </div>
        )}

        {share.warnings.length > 0 && (
          <Alert className="border-border-strong">
            <AlertTitle>开启前请留意</AlertTitle>
            <AlertDescription>
              <ul className="m-0 list-disc pl-4">
                {share.warnings.map((w) => <li key={w}>{w}</li>)}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <ShareSettingsForm share={share} saving={saving} onSave={onSave} />
      </div>
    </section>
  )
}
