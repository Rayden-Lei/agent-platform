import { Menu } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { useLocation } from 'react-router-dom'
import { activeNavKey, visibleNavItems } from '../../constants/nav'
import { useAuth } from '../../store/auth'
import { useGuardedNavigate } from '../../hooks/useGuardedNavigate'

// 侧边导航：菜单按角色过滤（docs/01 第 3 节权限矩阵），详情页高亮父菜单；有未保存改动时先确认再跳转。
interface Props { onNavigate?: () => void }

export default function SideNav({ onNavigate }: Props) {
  const location = useLocation()
  const role = useAuth((s) => s.user?.role)
  const guardedNavigate = useGuardedNavigate()
  const go = (key: string) => guardedNavigate(key, onNavigate)

  return (
    <>
      <div className="brand-logo">
        <div className="brand-logo-icon"><RobotOutlined /></div>
        <div style={{ fontSize: 15, fontWeight: 600, lineHeight: 1.2 }}>智枢·智能体平台</div>
      </div>
      <Menu
        mode="inline"
        theme="dark"
        selectedKeys={[activeNavKey(location.pathname)]}
        items={visibleNavItems(role).map((i) => ({ key: i.key, icon: i.icon, label: i.label }))}
        onClick={(e) => go(e.key)}
        style={{ background: 'transparent' }}
      />
    </>
  )
}
