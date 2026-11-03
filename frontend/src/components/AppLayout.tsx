import { Suspense, useEffect, useRef, useState } from 'react'
import { Button, Drawer, Dropdown, Skeleton, message } from 'antd'
import { DownOutlined, LogoutOutlined, MenuOutlined, UserOutlined } from '@ant-design/icons'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../store/auth'
import { useUnsaved } from '../store/unsaved'
import { useTheme } from '../store/theme'
import { navTitle } from '../constants/nav'
import { roleLabel } from '../constants/status'
import SideNav from './layout/SideNav'
import DegradedBanner from './layout/DegradedBanner'
import ForcePasswordModal from './layout/ForcePasswordModal'
import AppearanceMenu from './theme/AppearanceMenu'
import { useLiquidGlass } from '../hooks/useLiquidGlass'
import { changeMyPassword } from '../api'
import { useSessionSync } from '../hooks/useSessionSync'

// 应用主框架：左侧玻璃导航 + 顶部玻璃栏 + 内容区。
// 页面背景铺一层光斑与点阵（styles/theme.css 的 .page-blobs / .page-dots），玻璃才有东西可糊。
// 移动端侧栏收进抽屉；断点用 CSS（lg）判断，不再依赖 antd Grid 的 JS 断点。
export default function AppLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, setAuth } = useAuth()
  const dirty = useUnsaved((s) => s.dirty)
  const glass = useTheme((s) => s.glass)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [isMobile, setIsMobile] = useState(() => typeof window !== 'undefined' && window.innerWidth < 1024)
  useSessionSync() // 进入应用与切回页面时刷新角色、菜单与"必须改密"（docs/15 OP-02）

  // 顶栏与侧栏的玻璃滤镜（关闭玻璃时不生成贴图）
  const headerRef = useLiquidGlass<HTMLElement>({ enabled: glass })
  const sideRef = useLiquidGlass<HTMLDivElement>({ enabled: glass })

  // 视口宽度变化时切换移动端形态
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 1024)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // 必须改密：改完旧令牌全部失效（token_version +1），先换上新令牌再整页重载，免得页面上还在跑的请求带着旧令牌 401 被踢回登录页
  const changePassword = async (oldPassword: string, newPassword: string) => {
    const r = await changeMyPassword({ old_password: oldPassword, new_password: newPassword })
    setAuth(r.token, r.user)
    message.success('密码已修改')
    window.location.reload()
  }

  // 有未保存改动时拦刷新 / 关闭标签页（路由内跳转由 SideNav 拦）
  useEffect(() => {
    if (!dirty) return
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  return (
    <div className="relative h-full overflow-hidden flex" style={{ background: 'var(--bg)' }}>
      {/* 背景光斑与点阵：纯装饰，不接收事件 */}
      <div className="page-blobs" aria-hidden="true" />
      <div className="page-dots" aria-hidden="true" />

      {/* 侧栏：桌面固定，移动端抽屉 */}
      {isMobile ? (
        <Drawer
          placement="left"
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
          width={224}
          closable={false}
          styles={{ body: { padding: 0, background: 'var(--bg-soft-2)' } }}
          title={null}
        >
          <SideNav onNavigate={() => setDrawerOpen(false)} />
        </Drawer>
      ) : (
        <div
          ref={sideRef}
          className="lg shrink-0 h-full overflow-y-auto"
          style={{ width: 212, borderRadius: 0, borderWidth: '0 1px 0 0', borderStyle: 'solid', borderColor: 'var(--border)' }}
        >
          <SideNav />
        </div>
      )}

      <div className="flex-1 flex flex-col min-w-0 relative z-[1]">
        {/* 顶栏 */}
        <header
          ref={headerRef}
          className="lg shrink-0 flex items-center justify-between gap-3 px-4 sm:px-5"
          style={{ height: 56, borderRadius: 0, borderWidth: '0 0 1px 0', borderStyle: 'solid', borderColor: 'var(--border)' }}
        >
          <div className="flex items-center gap-2 min-w-0">
            {isMobile && (
              <Button type="text" icon={<MenuOutlined />} onClick={() => setDrawerOpen(true)} aria-label="打开菜单" />
            )}
            <span className="text-[15px] font-semibold truncate" style={{ color: 'var(--fg)' }}>
              {navTitle(location.pathname)}
            </span>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <AppearanceMenu />
            {/* 用户信息：头像取用户名首字母，点开是个人中心与退出登录（docs/15 OP-03） */}
            <Dropdown
              trigger={['click']}
              menu={{
                items: [
                  { key: 'profile', icon: <UserOutlined />, label: '个人中心', onClick: () => navigate('/profile') },
                  { type: 'divider' },
                  { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', onClick: () => { logout(); navigate('/login') } },
                ],
              }}
            >
              <button
                type="button"
                aria-label="账号菜单"
                className="flex items-center gap-2 h-9 px-1.5 rounded-lg transition-colors"
              >
                <span
                  className="w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-semibold shrink-0"
                  style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}
                >
                  {user?.username?.[0]?.toUpperCase()}
                </span>
                <span className="hidden sm:inline text-[13px]" style={{ color: 'var(--fg)' }}>{user?.username}</span>
                <span className="hidden md:inline text-[12px]" style={{ color: 'var(--fg-subtle)' }}>
                  {roleLabel[user?.role] || user?.role}
                </span>
                <DownOutlined style={{ fontSize: 10, color: 'var(--fg-subtle)' }} />
              </button>
            </Dropdown>
          </div>
        </header>

        <DegradedBanner />

        {/* 内容区：外层负责占位与内边距（min-height: 0 保证 flex 子项可收缩），页面自身滚动由各页面内部处理 */}
        <main className="flex-1 min-h-0 flex flex-col overflow-hidden" style={{ padding: isMobile ? 12 : 20 }}>
          <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
            <Suspense fallback={<Skeleton active paragraph={{ rows: 8 }} style={{ padding: 8 }} />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>

      <ForcePasswordModal
        open={!!user?.must_change_password}
        username={user?.username}
        onSubmit={changePassword}
        onLogout={() => { logout(); navigate('/login') }}
      />
    </div>
  )
}
