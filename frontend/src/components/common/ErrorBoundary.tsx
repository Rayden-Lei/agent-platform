import { Component, type ErrorInfo, type ReactNode } from 'react'

// 局部错误边界：某个区块渲染抛错时只降级这一块，不把整棵应用树卸掉。
//
// 为什么需要它：2026-11-06 分享链接对话在模型出字那一刻整页白屏 —— 根因是 ThinkingTrace 的
// hook 顺序错了（已修）。但 React 的默认行为是「渲染期抛错 = 卸载整棵树」，一个消息组件的
// 边界情况就能让使用者失去整个页面，连切换会话都点不到。对话流这种「内容由模型生成、
// 结构不可预知」的地方必须有兜底：出问题时只损失这一条消息，输入框与其它消息都还在。
//
// 用法：包在可能出问题的区块外层（单条消息、Markdown 正文、图表），不要包整页 ——
// 整页级兜底会掩盖问题，且降级后没有可操作的内容。
interface Props {
  children: ReactNode
  /** 降级时显示的内容；不传用通用文案 */
  fallback?: ReactNode
  /** 出错时上报（默认打到 console.error，带组件栈） */
  onError?: (error: Error, info: ErrorInfo) => void
}

interface State { error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    if (this.props.onError) this.props.onError(error, info)
    else console.error('区块渲染失败：', error, info.componentStack)
  }

  // 重试：清掉 error 让它再渲染一次（数据刚到达时的一次性异常很常见）。
  // 父级换了一条消息时 key 变化会让 React 重建实例，不需要手动 reset。
  private retry = () => this.setState({ error: null })

  render() {
    if (!this.state.error) return this.props.children
    if (this.props.fallback) return this.props.fallback
    return (
      <div
        className="flex flex-wrap items-center gap-2 rounded-lg px-3 py-2 text-[12.5px]"
        style={{ background: 'var(--bg-soft)', border: '1px solid var(--border)', color: 'var(--fg-muted)' }}
        role="alert"
      >
        <span>这段内容渲染失败，已跳过（不影响其它消息）</span>
        <button
          type="button"
          onClick={this.retry}
          className="rounded-md px-1.5 py-0.5 text-[12px] hover:bg-accent"
          style={{ color: 'var(--accent)' }}
        >
          重试
        </button>
      </div>
    )
  }
}
