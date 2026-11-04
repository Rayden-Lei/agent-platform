import { Copy } from 'lucide-react'
import { toast } from 'sonner'
import Modal from '../ui/Modal'
import Button from '../ui/Button'

// 新生成的 API Key 只显示一次：提供复制按钮，关闭后不可再查看。
// 明文放在可手动选中的块里 —— http 下浏览器可能不给剪贴板，此时用户还能选中复制。
// dismissible={false}：点遮罩或按 ESC 都不关，避免手一抖把只看一次的 key 弄丢。
interface Props { value: string | null; onClose: () => void }

export default function CreatedKeyModal({ value, onClose }: Props) {
  const copy = async () => {
    try { await navigator.clipboard.writeText(value ?? ''); toast.success('已复制到剪贴板') }
    catch { toast.warning('浏览器不允许自动复制，请手动选中复制') }
  }

  return (
    <Modal
      open={!!value}
      size="sm"
      dismissible={false}
      title="API Key 已生成（仅显示一次，请复制保存）"
      onClose={onClose}
      footer={
        <>
          <Button icon={<Copy className="size-3.5" />} onClick={copy}>复制</Button>
          <Button variant="primary" onClick={onClose}>我已保存</Button>
        </>
      }
    >
      <div className="select-all break-all rounded-lg border border-border bg-secondary px-3 py-2.5 font-mono text-[13px] leading-relaxed text-foreground">{value}</div>
      <p className="mt-2.5 text-[12px] leading-relaxed text-muted-foreground">
        调用方式：请求头 <code className="font-mono">Authorization: Bearer {'<key>'}</code>。只能调用授权范围内的智能体与工作流（对话、会话、工作流运行接口），管理类接口不接受 API Key；每次请求消耗 1 次配额，被白名单拒绝或被限速的请求不消耗。
      </p>
    </Modal>
  )
}
