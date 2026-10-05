import { message } from 'antd'

// 复制到剪贴板并提示。http 下浏览器不提供剪贴板（navigator.clipboard 为空或拒绝），给出可见的失败提示，
// 调用处同时要把内容放在可手动选中的位置（docs/15 3.8：服务器目前只有 http）
export async function copyText(text: string, what = '') {
  try {
    await navigator.clipboard.writeText(text)
    message.success(`已复制${what}`)
  } catch {
    message.warning('浏览器不允许自动复制（http 下剪贴板不可用），请手动选中复制')
  }
}
