import { useEffect } from 'react'
import { useTheme } from '../../store/theme'

// 把主题与玻璃开关写到 <html> 上：CSS 变量按 data-theme 切换，玻璃按 data-glass 开关。
// 放在最外层，登录页与分享页也跟随（它们不套 AppLayout）。
export default function ThemeProvider({ children }: { children: React.ReactNode }) {
  const theme = useTheme((s) => s.theme)
  const glass = useTheme((s) => s.glass)

  useEffect(() => {
    const root = document.documentElement
    root.setAttribute('data-theme', theme)
    root.setAttribute('data-glass', glass ? 'on' : 'off')
  }, [theme, glass])

  return <>{children}</>
}
