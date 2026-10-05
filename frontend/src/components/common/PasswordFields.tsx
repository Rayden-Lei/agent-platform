import { Form, Input } from 'antd'

// 改密表单的三个字段（当前密码 / 新密码 / 确认）：强制改密弹窗与个人中心共用，规则与后端 ChangePasswordIn 一致（6～128 位、
// 不能与当前密码相同）；放在调用方的 <Form> 里用，字段名 old_password / new_password / confirm。
export interface PasswordValues { old_password: string; new_password: string; confirm: string }

export default function PasswordFields() {
  return (
    <>
      <Form.Item name="old_password" label="当前密码" rules={[{ required: true }]}><Input.Password autoComplete="current-password" /></Form.Item>
      <Form.Item name="new_password" label="新密码" dependencies={['old_password']}
        rules={[{ required: true }, { min: 6, max: 128, message: '6～128 位' }, ({ getFieldValue }) => ({ validator: (_, v) => (v && v === getFieldValue('old_password') ? Promise.reject(new Error('不能与当前密码相同')) : Promise.resolve()) })]}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
      <Form.Item name="confirm" label="确认新密码" dependencies={['new_password']}
        rules={[{ required: true }, ({ getFieldValue }) => ({ validator: (_, v) => (v === getFieldValue('new_password') ? Promise.resolve() : Promise.reject(new Error('两次输入不一致'))) })]}>
        <Input.Password autoComplete="new-password" />
      </Form.Item>
    </>
  )
}
