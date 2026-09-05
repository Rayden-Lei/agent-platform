import { Menu, Modal } from 'antd'
import { RobotOutlined } from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { activeNavKey, visibleNavItems } from '../../constants/nav'
import { useAuth } from '../../store/auth'
import { useUnsaved } from '../../store/unsaved'

// 侧边导航：菜单按角色过滤（docs/01 第 3 节权限矩阵），详情页高亮父菜单；有未保存改动时先确认再跳转。
interface Props { onNavigate?: () => void }

export default function SideNav({ onNavigate }: Props) {
  const navigate = useNavigate()
  const location = useLocation()
  const role = useAuth((s) => s.user?.role)
  const dirty = useUnsaved((s) => s.dirty)
  const setDirty = useUnsaved((s) => s.setDirty)

  const go = (key: string) => {
    const proceed = () => { setDirty(false); navigate(key); onNavigate?.() }
    if (dirty) Modal.confirm({ title: '有未保存的改动', content: '离开后修改会丢失，确定离开？', okText: '离开', okButtonProps: { danger: true }, onOk: proceed })
    else proceed()
  }

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
