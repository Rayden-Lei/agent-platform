import { useEffect } from 'react'
import { Button, DatePicker, Form, Input, InputNumber, Modal, Radio, Space, Switch, Typography } from 'antd'
import dayjs, { type Dayjs } from 'dayjs'
import type { AgentShare, AgentShareInput, ShareAccessMode } from '../../api'

// 分享链接的访问与限额设置（docs/15 3.6）：访问方式、访问密码、有效期、三个限额、访客能力。整体覆盖保存，开关状态沿用当前值。
// 密码三态：不设（有旧密码时清除）/ 保留现有 / 设置新密码；改密码或访问方式会让已打开页面的访客重新进入。数据与保存由页面注入。
type PasswordMode = 'none' | 'keep' | 'set'
interface Values {
  access_mode: ShareAccessMode
  password_mode: PasswordMode
  password?: string
  expires_at: Dayjs | null
  rate_limit_per_minute: number
  daily_message_limit: number
  visitor_daily_limit: number
  allow_http_tools: boolean
  show_citations: boolean
}
interface Props {
  share: AgentShare
  saving: boolean
  onSave: (input: AgentShareInput) => Promise<boolean>
}

const toValues = (s: AgentShare): Values => ({
  access_mode: s.access_mode, password_mode: s.password_set ? 'keep' : 'none', expires_at: s.expires_at ? dayjs(s.expires_at) : null,
  rate_limit_per_minute: s.rate_limit_per_minute, daily_message_limit: s.daily_message_limit, visitor_daily_limit: s.visitor_daily_limit,
  allow_http_tools: s.allow_http_tools, show_citations: s.show_citations,
})

export default function ShareSettingsForm({ share, saving, onSave }: Props) {
  const [form] = Form.useForm<Values>()
  const passwordMode = Form.useWatch('password_mode', form)
  useEffect(() => { form.setFieldsValue(toValues(share)) }, [share, form])

  const submit = async (v: Values) => {
    const input: AgentShareInput = {
      is_enabled: share.is_enabled, access_mode: v.access_mode, expires_at: v.expires_at ? v.expires_at.format() : null, // format() 是带偏移量的 ISO 8601
      rate_limit_per_minute: v.rate_limit_per_minute, daily_message_limit: v.daily_message_limit, visitor_daily_limit: v.visitor_daily_limit,
      allow_http_tools: v.allow_http_tools, show_citations: v.show_citations,
    }
    if (v.password_mode === 'set') input.password = v.password
    else if (v.password_mode === 'none' && share.password_set) input.password = null
    if (await onSave(input)) form.setFieldValue('password', undefined)
  }
  // 打开 HTTP 工具前确认：访客能触发智能体绑定的 HTTP 工具，等于把这些接口开放给拿到链接的人。
  // Form.Item 先把开关值写进表单再调这里，所以打开时先拨回关闭，确认后才置为打开（取消则保持关闭）
  const confirmHttpTools = (checked: boolean) => {
    if (!checked) return
    form.setFieldValue('allow_http_tools', false)
    Modal.confirm({
      title: '允许访客调用 HTTP 工具？', okText: '允许', cancelText: '取消',
      content: '访客的提问会触发智能体绑定的 HTTP 工具（预检里列出了是哪几个），等于把这些接口开放给拿到链接的人。保存后生效。',
      onOk: () => form.setFieldValue('allow_http_tools', true),
    })
  }

  return (
    <Form form={form} layout="vertical" onFinish={submit} initialValues={toValues(share)} style={{ maxWidth: 640 }}>
      <Form.Item name="access_mode" label="访问方式" extra="仅登录：访客用平台账号登录后访问，会话记在其本人名下，检索按其本人的角色">
        <Radio.Group options={[{ value: 'public', label: '公开（拿到链接即可）' }, { value: 'login', label: '仅登录用户' }]} />
      </Form.Item>
      <Form.Item name="password_mode" label="访问密码">
        <Radio.Group options={[{ value: 'none', label: '不设' }, ...(share.password_set ? [{ value: 'keep', label: '保留现有密码' }] : []), { value: 'set', label: share.password_set ? '改成新密码' : '设置密码' }]} />
      </Form.Item>
      {passwordMode === 'set' && (
        <Form.Item name="password" rules={[{ required: true, message: '请输入访问密码' }, { min: 4, max: 64, message: '4～64 个字符' }]}>
          <Input.Password placeholder="4～64 个字符" autoComplete="new-password" style={{ maxWidth: 320 }} />
        </Form.Item>
      )}
      <Form.Item name="expires_at" label="有效期至" extra="不填则长期有效；过期后访客打开看到「链接已过期」">
        <DatePicker showTime allowClear disabledDate={(d) => d.isBefore(dayjs().startOf('day'))} />
      </Form.Item>
      <Space size={16} wrap>
        <Form.Item name="rate_limit_per_minute" label="整条链接每分钟" rules={[{ required: true }]}><InputNumber min={1} max={600} precision={0} addonAfter="次" /></Form.Item>
        <Form.Item name="daily_message_limit" label="整条链接每天" rules={[{ required: true }]}><InputNumber min={1} max={100000} precision={0} addonAfter="条" /></Form.Item>
        <Form.Item name="visitor_daily_limit" label="每位访客每天" rules={[{ required: true }]}><InputNumber min={1} max={1000} precision={0} addonAfter="条" /></Form.Item>
      </Space>
      <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: -8 }}>
        成本的硬上限是"整条链接每天"：访客换浏览器能绕开"每位访客每天"，绕不开它。超限的提问直接拒绝，不调模型。
      </Typography.Paragraph>
      <Space size={24} wrap>
        <Form.Item name="show_citations" label="显示引用来源" valuePropName="checked"><Switch /></Form.Item>
        <Form.Item name="allow_http_tools" label="允许 HTTP 工具" valuePropName="checked"><Switch onChange={confirmHttpTools} /></Form.Item>
      </Space>
      <Button type="primary" htmlType="submit" loading={saving}>保存设置</Button>
    </Form>
  )
}
