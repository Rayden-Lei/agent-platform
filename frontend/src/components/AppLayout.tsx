import { Suspense, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ChevronDown, LogOut, Menu, User } from 'lucide-react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Sheet, SheetContent } from '@/components/shadcn/sheet'
import { Skeleton } from '@/components/shadcn/skeleton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/shadcn/dropdown-menu'
import { useAuth } from '../store/auth'
import { useUnsaved } from '../store/unsaved'
import { useTheme } from '../store/theme'
import { navTitle } from '../constants/nav'
import { roleLabel } from '../constants/status'
import SideNav from './layout/SideNav'
import DegradedBanner from './layout/DegradedBanner'
import ForcePasswordModal from './layout/ForcePasswordModal'
import AppearanceMenu from './theme/AppearanceMenu'
import Button from './ui/Button'
import GlassSurface from './theme/GlassSurface'
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

  // 玻璃底色：关闭玻璃时退回实色，和 theme.css 的降级规则一致
  const glassOff = { background: 'var(--bg-elev)' }

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
    toast.success('密码已修改')
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
    <div className="relative flex h-full overflow-hidden" style={{ background: 'var(--bg)' }}>
      {/* 背景光斑与点阵：纯装饰，不接收事件 */}
      <div className="page-blobs" aria-hidden="true" />
      <div className="page-dots" aria-hidden="true" />

      {/* 侧栏：桌面固定，移动端抽屉 */}
      {isMobile ? (
        <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
          <SheetContent side="left" className="w-[224px] p-0" style={{ background: 'var(--bg-soft-2)' }}>
            <SideNav onNavigate={() => setDrawerOpen(false)} />
          </SheetContent>
        </Sheet>
      ) : (
        <div
          className="relative h-full shrink-0"
          style={{ width: 212, borderWidth: '0 1px 0 0', borderStyle: 'solid', borderColor: 'var(--border)', ...(glass ? null : glassOff) }}
        >
          <GlassSurface enabled={glass} />
          <div className="relative h-full overflow-y-auto">
            <SideNav />
          </div>
        </div>
      )}

      <div className="relative z-[1] flex min-w-0 flex-1 flex-col">
        {/* 顶栏 */}
        <header
          className="relative flex shrink-0 items-center justify-between gap-3 px-4 sm:px-5"
          style={{ height: 56, borderWidth: '0 0 1px 0', borderStyle: 'solid', borderColor: 'var(--border)', ...(glass ? null : glassOff) }}
        >
          <GlassSurface enabled={glass} />
          <div className="flex min-w-0 items-center gap-2">
            {isMobile && (
              <Button variant="ghost" size="sm" aria-label="打开菜单" onClick={() => setDrawerOpen(true)}>
                <Menu className="size-4" />
              </Button>
            )}
            <span className="truncate text-[15px] font-semibold" style={{ color: 'var(--fg)' }}>
              {navTitle(location.pathname)}
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            <AppearanceMenu />
            {/* 用户信息：头像取用户名首字母，点开是个人中心与退出登录（docs/15 OP-03） */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  aria-label="账号菜单"
                  className="flex h-9 items-center gap-2 rounded-lg px-1.5 transition-colors hover:bg-accent"
                >
                  <span className="flex size-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold" style={{ background: 'var(--accent)', color: 'var(--accent-fg)' }}>
                    {user?.username?.[0]?.toUpperCase()}
                  </span>
                  <span className="hidden text-[13px] sm:inline" style={{ color: 'var(--fg)' }}>{user?.username}</span>
                  <span className="hidden text-[12px] md:inline" style={{ color: 'var(--fg-subtle)' }}>
                    {roleLabel[user?.role] || user?.role}
                  </span>
                  <ChevronDown className="size-3.5 text-muted-foreground" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-40">
                <DropdownMenuItem onSelect={() => navigate('/profile')}>
                  <User className="size-3.5" />个人中心
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => { logout(); navigate('/login') }}>
                  <LogOut className="size-3.5" />退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>

        <DegradedBanner />

        {/* 内容区：外层负责占位与内边距（min-height: 0 保证 flex 子项可收缩），页面自身滚动由各页面内部处理 */}
        <main className="flex min-h-0 flex-1 flex-col overflow-hidden" style={{ padding: isMobile ? 12 : 20 }}>
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <Suspense fallback={<div className="flex flex-col gap-2 p-2"><Skeleton className="h-5 w-40" /><Skeleton className="h-32 w-full" /><Skeleton className="h-32 w-full" /></div>}>
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
