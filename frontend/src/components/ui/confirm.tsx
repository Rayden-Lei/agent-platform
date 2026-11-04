import { useEffect, useState } from 'react'
import Modal from './Modal'
import Button from './Button'

// 全局二次确认：替代 antd 的 Modal.confirm。
// hook / 工具函数里不能渲染组件，所以这里用模块级队列 + 挂在根部的 <ConfirmHost />。
// 用法：if (await confirm({ title: '离开？', content: '改动会丢失' })) {...}
interface Options {
  title: string
  content?: string
  okText?: string
  cancelText?: string
  danger?: boolean
}

interface Pending extends Options {
  resolve: (ok: boolean) => void
}

let pending: Pending | null = null
const listeners = new Set<(p: Pending | null) => void>()

function emit() {
  for (const fn of listeners) fn(pending)
}

export function confirm(options: Options): Promise<boolean> {
  // 同时只允许一个确认框：后来的排队没有意义，直接覆盖前一个（前一个按取消处理）
  if (pending) pending.resolve(false)
  return new Promise<boolean>((resolve) => {
    pending = { ...options, resolve }
    emit()
  })
}

function settle(ok: boolean) {
  const p = pending
  pending = null
  emit()
  p?.resolve(ok)
}

export function ConfirmHost() {
  const [state, setState] = useState<Pending | null>(pending)

  useEffect(() => {
    listeners.add(setState)
    return () => { listeners.delete(setState) }
  }, [])

  return (
    <Modal
      open={!!state}
      size="sm"
      title={state?.title ?? ''}
      onClose={() => settle(false)}
      footer={
        <>
          <Button variant="ghost" size="md" onClick={() => settle(false)}>{state?.cancelText ?? '取消'}</Button>
          <Button variant={state?.danger ? 'danger' : 'primary'} size="md" onClick={() => settle(true)}>{state?.okText ?? '确定'}</Button>
        </>
      }
    >
      {state?.content && <p className="m-0 text-[13px] leading-relaxed text-muted-foreground">{state.content}</p>}
    </Modal>
  )
}
