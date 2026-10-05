import { Alert, Button, Card, Popconfirm, Popover, QRCode, Space, Switch, Typography } from 'antd'
import { CopyOutlined, ExportOutlined, QrcodeOutlined, ReloadOutlined } from '@ant-design/icons'
import type { AgentShare, AgentShareInput } from '../../api'
import ErrorState from '../common/ErrorState'
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
  if (error) return <Card size="small" title="分享链接"><ErrorState compact message={error} onRetry={onRetry} /></Card>
  if (!share) return <Card size="small" title="分享链接" loading />
  const url = share.code ? share.share_url || `${window.location.origin}/s/${share.code}` : null
  const toggle = (checked: boolean) => onSave({ ...configOf(share), is_enabled: checked }, checked ? '分享已开启' : '分享已关闭：链接立即失效')

  return (
    <Card size="small" title="分享链接"
      extra={<Space><Typography.Text type="secondary">{share.is_enabled ? '已开启' : '未开启'}</Typography.Text>
        <Switch checked={share.is_enabled} loading={saving} disabled={!share.published && !share.is_enabled} onChange={toggle} /></Space>}>
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        <Typography.Text type="secondary">生成一个体验链接，不登录平台也能和线上版本对话；访客只看到回答与引用，看不到提示词、模型、工具入参与运行记录。</Typography.Text>
        {!share.published && <Alert type="warning" showIcon message="智能体还没有发布：发布后才能开启分享" />}
        {url && (
          <Space wrap>
            {/* http 下剪贴板不可用：链接放在可手动全选的位置 */}
            <Typography.Text code style={{ userSelect: 'all', wordBreak: 'break-all' }}>{url}</Typography.Text>
            <Button size="small" icon={<CopyOutlined />} onClick={() => copyText(url, '分享链接')}>复制</Button>
            <Popover trigger="click" content={<QRCode value={url} size={160} bordered={false} />}><Button size="small" icon={<QrcodeOutlined />}>二维码</Button></Popover>
            <Button size="small" icon={<ExportOutlined />} href={url} target="_blank" rel="noopener noreferrer" disabled={!share.is_enabled}>新窗口预览</Button>
            <Popconfirm title="重置链接？" description="换一个新地址，旧链接与已打开页面的访客立即失效，需要把新链接重新发给大家" okText="重置" okButtonProps={{ danger: true }} onConfirm={onReset}>
              <Button size="small" danger icon={<ReloadOutlined />}>重置链接</Button>
            </Popconfirm>
          </Space>
        )}
        {share.warnings.length > 0 && (
          <Alert type="warning" showIcon message="开启前请留意" description={<ul style={{ margin: 0, paddingLeft: 18 }}>{share.warnings.map((w) => <li key={w}>{w}</li>)}</ul>} />
        )}
        <ShareSettingsForm share={share} saving={saving} onSave={onSave} />
      </Space>
    </Card>
  )
}
