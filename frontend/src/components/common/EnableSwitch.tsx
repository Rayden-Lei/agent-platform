import { useState } from 'react'
import { Switch, message } from 'antd'
import { errorText } from '../../utils/errors'

// 列内启停开关：乐观更新，失败回滚并提示；请求中禁用防连点。
interface Props {
  checked: boolean
  onToggle: () => Promise<unknown>
  disabled?: boolean
  size?: 'small' | 'default'
}

export default function EnableSwitch({ checked, onToggle, disabled, size = 'small' }: Props) {
  const [pending, setPending] = useState(false)
  const [optimistic, setOptimistic] = useState<boolean | null>(null)
  const value = optimistic ?? checked
  const change = async () => {
    setOptimistic(!checked)
    setPending(true)
    try {
      await onToggle()
    } catch (e) {
      message.error(errorText(e, '操作失败'))
    } finally {
      setOptimistic(null)
      setPending(false)
    }
  }
  return <Switch size={size} checked={value} loading={pending} disabled={disabled} onChange={change} />
}
