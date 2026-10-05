import { useCallback, useEffect, useState } from 'react'
import { message } from 'antd'
import { RequestError, clearShareToken, createShareSession, getShareInfo, getShareToken, type ShareInfo } from '../api'
import { clearLoginAndRedirect } from '../api/client'

// 访客进入分享页的流程（docs/15 3.6）：取资料 → 已有本链接的访客令牌就直接进入；没有则按访问方式领令牌
// （"仅登录"要先有平台登录态，有访问密码先输密码）。之后任何访客请求 401（改了密码、重置链接、账号停用）都回到这里重新进入。
export type SharePhase = 'loading' | 'password' | 'login' | 'ready' | 'closed' | 'expired' | 'offline' | 'unavailable' | 'error'

// 资料与建会话的拒绝 → 状态页；文案与后端 share_service 一致
function phaseOf(e: unknown): SharePhase {
  if (!(e instanceof RequestError)) return 'error'
  if (e.status === 404) return 'closed'
  if (e.status === 403 && e.message === '链接已过期') return 'expired'
  if (e.status === 403 && /智能体已下线|智能体未发布/.test(e.message)) return 'offline'
  if (e.status === 403 && e.message === '分享不可用') return 'unavailable'
  return 'error'
}

export function useShareAccess(code: string) {
  const [phase, setPhase] = useState<SharePhase>('loading')
  const [info, setInfo] = useState<ShareInfo | null>(null)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [entering, setEntering] = useState(false)

  const fail = useCallback((e: unknown) => { setPhase(phaseOf(e)); setErrorMessage((e as Error).message || '加载失败') }, [])

  const enter = useCallback(async (current: ShareInfo, password?: string) => {
    if (getShareToken(code)) { setPhase('ready'); return } // 令牌失效时第一个访客请求会 401，再回到这里
    const needLogin = current.access_mode === 'login'
    if (needLogin && !localStorage.getItem('token')) { setPhase('login'); return }
    if (current.password_required && password === undefined) { setPhase('password'); return }
    setEntering(true)
    try {
      await createShareSession(code, password, needLogin)
      setPasswordError(null)
      setPhase('ready')
    } catch (e) {
      if (e instanceof RequestError && e.status === 401 && e.message === '访问密码错误') { setPasswordError(e.message); setPhase('password') }
      else if (e instanceof RequestError && e.status === 401 && needLogin) setPhase('login') // 平台登录已失效
      else fail(e)
    } finally {
      setEntering(false)
    }
  }, [code, fail])

  const load = useCallback(async () => {
    setPhase('loading')
    try {
      const got = await getShareInfo(code)
      setInfo(got)
      await enter(got)
    } catch (e) { fail(e) }
  }, [code, enter, fail])
  useEffect(() => { load() }, [load])

  // 访客请求 401：丢掉本地令牌，重新取资料再进入（分享可能已关闭或改了访问方式）
  const reenter = useCallback((detail?: string) => {
    clearShareToken(code)
    message.warning(detail || '访问凭证已失效，请重新进入')
    load()
  }, [code, load])
  // "仅登录"：去登录页，登录后回到本链接；平台登录态已失效的一并清掉
  const goLogin = () => clearLoginAndRedirect('登录后即可访问这个分享链接')

  return { phase, info, errorMessage, passwordError, entering, retry: load, reenter, goLogin,
    submitPassword: (password: string) => (info ? enter(info, password) : Promise.resolve()) }
}
