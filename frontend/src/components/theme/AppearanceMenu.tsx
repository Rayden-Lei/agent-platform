import { useEffect, useRef, useState } from 'react'
import { THEMES, currentThemeMeta, useTheme } from '../../store/theme'

// 外观设置：主题配色 + 玻璃效果开关，合在一个面板里（顶栏右侧）。
// 主题切换只改 <html data-theme>，8 套配色共用同一套组件结构，不触发任何组件重渲染。
export default function AppearanceMenu() {
  const theme = useTheme((s) => s.theme)
  const setTheme = useTheme((s) => s.setTheme)
  const glass = useTheme((s) => s.glass)
  const toggleGlass = useTheme((s) => s.toggleGlass)
  const [open, setOpen] = useState(false)
  const boxRef = useRef<HTMLDivElement>(null)
  const meta = currentThemeMeta(theme)

  // 点外部或按 Esc 关闭
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="外观设置"
        aria-expanded={open}
        className="flex items-center gap-2 h-9 px-2.5 rounded-lg text-[13px] transition-colors"
        style={{ color: 'var(--fg-muted)' }}
      >
        <span
          className="w-4 h-4 rounded-full shrink-0"
          style={{ background: meta.accent, boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.08)' }}
        />
        <span className="hidden sm:inline">{meta.name}</span>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .18s' }}>
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open && (
        <div
          className="absolute right-0 top-11 w-[268px] rounded-xl p-3.5 z-50"
          style={{
            background: 'var(--bg-elev)',
            border: '1px solid var(--border)',
            boxShadow: '0 16px 48px -12px rgba(8,12,24,.28)',
          }}
        >
          <div className="text-[10px] tracking-[1.2px] uppercase font-semibold mb-2.5" style={{ color: 'var(--fg-subtle)' }}>
            主题配色
          </div>
          <div className="grid grid-cols-4 gap-1.5 mb-4">
            {THEMES.map((t) => {
              const active = t.key === theme
              return (
                <button
                  key={t.key}
                  type="button"
                  onClick={() => setTheme(t.key)}
                  title={t.name}
                  aria-label={t.name}
                  aria-pressed={active}
                  className="flex flex-col items-center gap-1 py-1.5 rounded-lg transition-colors"
                  style={{
                    background: active ? 'var(--accent-soft)' : 'transparent',
                    outline: active ? '1px solid var(--accent)' : 'none',
                    outlineOffset: -1,
                  }}
                >
                  <span
                    className="w-6 h-6 rounded-full"
                    style={{ background: t.accent, boxShadow: 'inset 0 0 0 1px rgba(0,0,0,.08)' }}
                  />
                  <span className="text-[10.5px] leading-none" style={{ color: active ? 'var(--fg)' : 'var(--fg-muted)' }}>
                    {t.name}
                  </span>
                </button>
              )
            })}
          </div>

          <div className="h-px my-1" style={{ background: 'var(--border)' }} />

          <div className="flex items-center justify-between mt-2.5">
            <div>
              <div className="text-[13px]" style={{ color: 'var(--fg)' }}>玻璃效果</div>
              <div className="text-[11px] mt-0.5" style={{ color: 'var(--fg-subtle)' }}>低端设备可关闭以提性能</div>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={glass}
              aria-label="玻璃效果"
              onClick={toggleGlass}
              className="relative w-9 h-5 rounded-full transition-colors shrink-0"
              style={{ background: glass ? 'var(--accent)' : 'var(--border-strong)' }}
            >
              <span
                className="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
                style={{ left: 2, transform: glass ? 'translateX(16px)' : 'none' }}
              />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
