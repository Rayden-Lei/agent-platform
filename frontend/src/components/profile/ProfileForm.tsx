import { useEffect } from 'react'
import { Button, Form, Input, Popconfirm, Space, Typography } from 'antd'
import type { MeInfo, ProfileInput } from '../../api'

// 个人中心"基本资料"（docs/15 OP-03）：显示名、邮箱、手机号。用户名与角色只有管理员能改，这里只读。
// 手机号接口只给脱敏值：输入框留空表示不改，"清除"单独一个按钮；保存由页面注入。
interface Props {
  me: MeInfo
  saving: boolean
  onSave: (input: ProfileInput) => Promise<boolean>
}
interface Values { display_name?: string; email?: string; phone?: string }

export default function ProfileForm({ me, saving, onSave }: Props) {
  const [form] = Form.useForm<Values>()
  useEffect(() => { form.setFieldsValue({ display_name: me.display_name ?? '', email: me.email ?? '', phone: '' }) }, [me, form])

  const submit = async (v: Values) => {
    const input: ProfileInput = { display_name: v.display_name?.trim() || null, email: v.email?.trim() || null }
    if (v.phone?.trim()) input.phone = v.phone.trim()
    if (await onSave(input)) form.setFieldValue('phone', '')
  }

  return (
    <Form form={form} layout="vertical" onFinish={submit} style={{ maxWidth: 420 }}>
      <Form.Item label="用户名"><Typography.Text>{me.username}</Typography.Text></Form.Item>
      <Form.Item name="display_name" label="显示名" rules={[{ max: 64 }]}><Input placeholder="不填则显示用户名" /></Form.Item>
      <Form.Item name="email" label="邮箱" rules={[{ type: 'email', message: '邮箱格式不正确' }, { max: 128 }]}><Input placeholder="name@example.com" /></Form.Item>
      <Form.Item label="手机号" extra={me.phone_masked ? `当前：${me.phone_masked}（留空不改）` : '未设置'}>
        <Space.Compact style={{ width: '100%' }}>
          <Form.Item name="phone" noStyle rules={[{ pattern: /^\+?[0-9][0-9-]{4,19}$/, message: '5～20 位数字，可带 + 与 -' }]}>
            <Input placeholder={me.phone_masked ? '输入新号码以修改' : '输入手机号'} inputMode="tel" />
          </Form.Item>
          {me.phone_masked && (
            <Popconfirm title="清除手机号？" onConfirm={() => onSave({ phone: null })}><Button>清除</Button></Popconfirm>
          )}
        </Space.Compact>
      </Form.Item>
      <Button type="primary" htmlType="submit" loading={saving}>保存</Button>
    </Form>
  )
}
