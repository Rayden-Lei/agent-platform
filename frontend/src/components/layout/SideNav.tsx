import { RobotOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { activeNavKey, visibleNavItems } from '../../constants/nav'
import { useAuth } from '../../store/auth'
import { useGuardedNavigate } from '../../hooks/useGuardedNavigate'

// 侧边导航：菜单按角色过滤（docs/01 第 3 节权限矩阵），详情页高亮父菜单；有未保存改动时先确认再跳转。
// 视觉走新的浅色玻璃侧栏，不再用 antd Menu（迁移期两套并存，antd Menu 仅在其他页面内部还有用到）。
interface Props { onNavigate?: () => void }

export default function SideNav({ onNavigate }: Props) {
  const location = useLocation()
  const role = useAuth((s) => s.user?.role)
  const guardedNavigate = useGuardedNavigate()
  const current = activeNavKey(location.pathname)
  const go = (key: string) => guardedNavigate(key, onNavigate)

  return (
    <div className="h-full flex flex-col" style={{ padding: '14px 10px' }}>
      {/* 品牌区 */}
      <div className="flex items-center gap-2 px-2 pb-4">
        <div
          className="w-[26px] h-[26px] rounded-[7px] flex items-center justify-center shrink-0 text-[13px]"
          style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
        >
          <RobotOutlined />
        </div>
        <div className="text-[13.5px] font-semibold leading-tight" style={{ color: 'var(--fg)' }}>
          智枢<span style={{ color: 'var(--fg-subtle)' }}>·</span>智能体平台
        </div>
      </div>

      <nav className="flex-1 overflow-y-auto flex flex-col gap-0.5" aria-label="主导航">
        {visibleNavItems(role).map((item) => {
          const active = item.key === current
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => go(item.key)}
              aria-current={active ? 'page' : undefined}
              className="flex items-center gap-2.5 px-2.5 py-[7px] rounded-lg text-[13px] text-left transition-colors"
              style={{
                background: active ? 'var(--bg-elev)' : 'transparent',
                color: active ? 'var(--fg)' : 'var(--fg-muted)',
                fontWeight: active ? 550 : 400,
                boxShadow: active ? 'var(--shadow-card)' : 'none',
              }}
            >
              <span
                className="text-[15px] flex items-center shrink-0"
                style={{ color: active ? 'var(--accent)' : 'var(--fg-subtle)' }}
              >
                {item.icon}
              </span>
              <span className="truncate">{item.label}</span>
            </button>
          )
        })}
      </nav>
    </div>
  )
}
