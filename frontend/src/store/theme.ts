import { create } from 'zustand'

// 主题与玻璃开关：只存"选了什么"，真正的样式由 <html data-theme data-glass> + CSS 变量驱动。
// 持久化到 localStorage，刷新后保持。

export type ThemeKey = 'indigo' | 'celadon' | 'navy' | 'sand' | 'fuchsia' | 'graphite' | 'deep' | 'midnight'

export interface ThemeMeta {
  key: ThemeKey
  name: string
  en: string
  accent: string
  bg: string
  dark: boolean
}

// 主题清单：只用于渲染切换器色块与名称，实际颜色以 theme.css 为准（这里不重复定义 token）
export const THEMES: ThemeMeta[] = [
  { key: 'indigo', name: '清透', en: 'Indigo', accent: '#4F46E5', bg: '#F5F7FB', dark: false },
  { key: 'celadon', name: '青瓷', en: 'Celadon', accent: '#0F766E', bg: '#F2F6F5', dark: false },
  { key: 'navy', name: '墨蓝', en: 'Navy', accent: '#1E40AF', bg: '#F4F6FA', dark: false },
  { key: 'sand', name: '暖砂', en: 'Sand', accent: '#B45309', bg: '#F8F5F0', dark: false },
  { key: 'fuchsia', name: '品红', en: 'Fuchsia', accent: '#C026D3', bg: '#F9F5FB', dark: false },
  { key: 'graphite', name: '石墨', en: 'Graphite', accent: '#27272A', bg: '#F6F6F7', dark: false },
  { key: 'deep', name: '深空', en: 'Deep Space', accent: '#7C93FF', bg: '#0A0C10', dark: true },
  { key: 'midnight', name: '夜紫', en: 'Night Violet', accent: '#A78BFA', bg: '#100A1A', dark: true },
]

const THEME_STORAGE_KEY = 'zs.theme'
const GLASS_STORAGE_KEY = 'zs.glass'

function applyToDom(theme: ThemeKey, glass: boolean) {
  const root = document.documentElement
  root.setAttribute('data-theme', theme)
  root.setAttribute('data-glass', glass ? 'on' : 'off')
}

function readTheme(): ThemeKey {
  try {
    const v = localStorage.getItem(THEME_STORAGE_KEY)
    if (v && THEMES.some((t) => t.key === v)) return v as ThemeKey
  } catch {
    // localStorage 不可用（隐私模式 / 禁用）时用默认主题，不阻断渲染
  }
  return 'indigo'
}

function readGlass(): boolean {
  try {
    const v = localStorage.getItem(GLASS_STORAGE_KEY)
    if (v === 'on') return true
    if (v === 'off') return false
  } catch {
    // 同上
  }
  return true
}

interface ThemeState {
  theme: ThemeKey
  glass: boolean
  setTheme: (t: ThemeKey) => void
  setGlass: (on: boolean) => void
  toggleGlass: () => void
}

export const useTheme = create<ThemeState>((set, get) => ({
  theme: readTheme(),
  glass: readGlass(),
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // 存不了就只在本次会话生效
    }
    // 属性必须在 React 重渲染之前写到 <html> 上：等 ThemeProvider 的 useEffect 去写的话，
    // 首帧取到的还是旧值，深色主题会闪一下白。
    applyToDom(theme, get().glass)
    set({ theme })
  },
  setGlass: (glass) => {
    try {
      localStorage.setItem(GLASS_STORAGE_KEY, glass ? 'on' : 'off')
    } catch {
      // 同上
    }
    applyToDom(get().theme, glass)
    set({ glass })
  },
  toggleGlass: () => get().setGlass(!get().glass),
}))

export function currentThemeMeta(theme: ThemeKey): ThemeMeta {
  return THEMES.find((t) => t.key === theme) ?? THEMES[0]
}
