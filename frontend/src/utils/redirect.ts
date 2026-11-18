// 登录回跳（docs/15 OP-02）：未登录访问 /runs/12 → 登录页带 redirect → 登录后回到 /runs/12。

const NOTICE_KEY = 'login_notice' // 被踢回登录页的原因（如"账号已停用"），登录页取出显示一次

// 只接受站内路径：以单个 / 开头；不是 // 或 /\（浏览器把反斜杠当斜杠，两者都会跳到外站）；不含控制字符。
// 其余（http:、javascript:、空）一律回首页，防开放重定向
export function safeRedirect(raw: string | null | undefined): string {
  // 控制字符是这里要显式拦截的输入（换行、`\0` 等能截断 Location 头或注入日志），
  // 不是误用正则，故对 no-control-regex 单条豁免
  // eslint-disable-next-line no-control-regex
  if (!raw || !raw.startsWith('/') || /^\/[/\\]/.test(raw) || /[\u0000-\u001f]/.test(raw)) return '/'
  return raw
}

// 当前所在页对应的登录地址；首页与登录页本身不带 redirect
export function loginPathFor(current: string): string {
  return current && current !== '/' && !current.startsWith('/login') ? `/login?redirect=${encodeURIComponent(current)}` : '/login'
}

export function setLoginNotice(text: string | undefined) {
  if (text) sessionStorage.setItem(NOTICE_KEY, text)
}

export function takeLoginNotice(): string | null {
  const text = sessionStorage.getItem(NOTICE_KEY)
  sessionStorage.removeItem(NOTICE_KEY)
  return text
}
