import { Button, Modal, Space, Typography, message } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

// 新生成的 API Key 只显示一次：提供复制按钮，关闭后不可再查看。
interface Props { value: string | null; onClose: () => void }

export default function CreatedKeyModal({ value, onClose }: Props) {
  const copy = async () => {
    try { await navigator.clipboard.writeText(value ?? ''); message.success('已复制到剪贴板') } catch { message.warning('浏览器不允许自动复制，请手动选中复制') }
  }
  return (
    <Modal title="API Key 已生成（仅显示一次，请复制保存）" open={!!value} onCancel={onClose} maskClosable={false} footer={<Space><Button icon={<CopyOutlined />} onClick={copy}>复制</Button><Button type="primary" onClick={onClose}>我已保存</Button></Space>}>
      <div style={{ background: '#f8fafc', border: '1px solid #e5e7eb', borderRadius: 6, padding: 12, fontFamily: 'monospace', wordBreak: 'break-all', userSelect: 'all' }}>{value}</div>
      <Typography.Paragraph type="secondary" style={{ marginTop: 10, fontSize: 12, lineHeight: 1.7, marginBottom: 0 }}>
        调用方式：请求头 <code>Authorization: Bearer {'<key>'}</code>。可调用对话、会话、工作流运行接口，管理类接口不接受 API Key；每次请求消耗 1 次配额，被白名单拒绝或被限速的请求不消耗。
      </Typography.Paragraph>
    </Modal>
  )
}
