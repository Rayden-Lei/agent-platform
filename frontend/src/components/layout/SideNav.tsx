import { Bot } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import { activeNavKey, visibleNavGroups } from '../../constants/nav'
import { useAuth } from '../../store/auth'
import { useGuardedNavigate } from '../../hooks/useGuardedNavigate'

// 侧边导航：菜单按角色过滤后分组（docs/17 §2 分组表），详情页高亮父菜单；有未保存改动时先确认再跳转。
// 视觉走新的浅色玻璃侧栏，导航项自绘（不在任何 UI 库里找 Menu）。
interface Props { onNavigate?: () => void }

export default function SideNav({ onNavigate }: Props) {
  const location = useLocation()
  const role = useAuth((s) => s.user?.role)
  const guardedNavigate = useGuardedNavigate()
  const current = activeNavKey(location.pathname)
  const go = (key: string) => guardedNavigate(key, onNavigate)
  const groups = visibleNavGroups(role)

  return (
    <div className="h-full flex flex-col" style={{ padding: '14px 10px' }}>
      {/* 品牌区 */}
      <div className="flex items-center gap-2 px-2 pb-3">
        <div
          className="w-[26px] h-[26px] rounded-[7px] flex items-center justify-center shrink-0 text-[13px]"
          style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
        >
          <Bot />
        </div>
        <div className="text-[13.5px] font-semibold leading-tight" style={{ color: 'var(--fg)' }}>
          智枢<span style={{ color: 'var(--fg-subtle)' }}>·</span>智能体平台
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto flex flex-col gap-1" aria-label="主导航">
        {groups.map((group, gi) => (
          <div key={group.key} className="flex flex-col gap-0.5">
            {/* 组标题：只做视觉分隔，不参与键盘导航；空组已在 visibleNavGroups 里过滤掉 */}
            <div
              className="px-2.5 text-[11px] font-medium tracking-wide"
              style={{ color: 'var(--fg-subtle)', marginTop: gi === 0 ? 0 : 8, marginBottom: 1 }}
            >
              {group.label}
            </div>
            {group.items.map((item) => {
              const active = item.key === current
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => go(item.key)}
                  aria-current={active ? 'page' : undefined}
                  className="flex items-center gap-2.5 px-2.5 py-[6px] rounded-lg text-[13px] text-left transition-colors"
                  style={{
                    background: active ? 'var(--bg-elev)' : 'transparent',
                    color: active ? 'var(--fg)' : 'var(--fg-muted)',
                    fontWeight: active ? 550 : 400,
                    boxShadow: active ? 'var(--shadow-card)' : 'none',
                  }}
                >
                  <span
                    className="text-[15px] flex items-center shrink-0 [&>svg]:size-[15px]"
                    style={{ color: active ? 'var(--accent)' : 'var(--fg-subtle)' }}
                  >
                    {item.icon}
                  </span>
                  <span className="truncate">{item.label}</span>
                </button>
              )
            })}
          </div>
        ))}
      </nav>
    </div>
  )
}
