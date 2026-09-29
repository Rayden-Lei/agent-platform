import { useCallback } from 'react'
import { Modal } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useUnsaved } from '../store/unsaved'

// 带未保存拦截的站内跳转：有未保存改动时先确认，确认离开才清标记并跳转。菜单与编辑器页内的"返回"共用。
// BrowserRouter + <Routes> 下没有 useBlocker，浏览器后退键拦不住（刷新 / 关标签页由 AppLayout 的 beforeunload 拦）。
export function useGuardedNavigate() {
  const navigate = useNavigate()
  const dirty = useUnsaved((s) => s.dirty)
  const setDirty = useUnsaved((s) => s.setDirty)
  return useCallback((to: string, afterLeave?: () => void) => {
    const proceed = () => { setDirty(false); navigate(to); afterLeave?.() }
    if (dirty) Modal.confirm({ title: '有未保存的改动', content: '离开后修改会丢失，确定离开？', okText: '离开', okButtonProps: { danger: true }, onOk: proceed })
    else proceed()
  }, [dirty, navigate, setDirty])
}
