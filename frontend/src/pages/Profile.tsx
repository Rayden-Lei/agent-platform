import { useState } from 'react'
import { Tag, message } from 'antd'
import { changeMyPassword, listMyApiKeys, listMyLogins, logoutOtherDevices, me, updateMe, type ProfileInput } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useAuth } from '../store/auth'
import { roleLabel } from '../constants/status'
import DetailPage from '../components/layout/DetailPage'
import ProfileForm from '../components/profile/ProfileForm'
import SecurityPanel from '../components/profile/SecurityPanel'
import MyApiKeysPanel from '../components/profile/MyApiKeysPanel'
import LoginHistoryTable from '../components/profile/LoginHistoryTable'
import { errorText } from '../utils/errors'
import { formatDateTime } from '../utils/time'

// 个人中心 /profile（docs/15 OP-03，从顶栏头像进入）：基本资料、密码与安全、我的 API 密钥、登录记录，?tab= 深链。
// 取数与保存都在本页面，子组件只接收 props。改密与退出其他设备成功后换上服务端返回的新令牌，当前页面不掉线。
export default function Profile() {
  const { user, setAuth } = useAuth()
  const canManageKeys = user?.role === 'admin' || user?.role === 'developer'
  const profile = useAsyncData(me, [], { errorText: '加载个人信息失败' })
  const logins = useAsyncData(listMyLogins, [], { errorText: '加载登录记录失败' })
  const keys = useAsyncData(() => listMyApiKeys({ page: 1, page_size: 50 }), [], { errorText: '加载 API Key 失败' })
  const [saving, setSaving] = useState(false)

  const saveProfile = async (input: ProfileInput) => {
    setSaving(true)
    try {
      profile.setData(await updateMe(input))
      message.success('已保存')
      return true
    } catch (e) {
      message.error(errorText(e, '保存失败'))
      return false
    } finally { setSaving(false) }
  }
  const changePassword = async (oldPassword: string, newPassword: string) => {
    const r = await changeMyPassword({ old_password: oldPassword, new_password: newPassword })
    setAuth(r.token, r.user)
    profile.reload(true)
  }
  const logoutOthers = async () => {
    const r = await logoutOtherDevices()
    setAuth(r.token, r.user)
  }

  const info = profile.data
  return (
    <DetailPage
      crumbs={[{ label: '个人中心' }]}
      title={info ? info.display_name || info.username : ''}
      tags={info && <Tag>{roleLabel[info.role] || info.role}</Tag>}
      meta={info ? [
        { label: '用户名', value: info.username },
        { label: '最近登录', value: info.last_login_at ? formatDateTime(info.last_login_at) : '-' },
        { label: '最近改密', value: info.password_changed_at ? formatDateTime(info.password_changed_at) : '-' },
      ] : []}
      loading={profile.loading && !info}
      error={profile.error}
      onRetry={() => profile.reload()}
      backTo="/"
      tabs={info ? [
        { key: 'basic', label: '基本资料', children: <ProfileForm me={info} saving={saving} onSave={saveProfile} /> },
        { key: 'security', label: '密码与安全', children: <SecurityPanel passwordChangedAt={info.password_changed_at} onChangePassword={changePassword} onLogoutOthers={logoutOthers} /> },
        {
          key: 'keys', label: '我的 API 密钥', children: (
            <MyApiKeysPanel keys={keys.data?.items ?? null} total={keys.data?.total} error={keys.error} onRetry={() => keys.reload()}
              canManage={canManageKeys} apiBase={`${info.public_base_url || window.location.origin}/api/v1`} />
          ),
        },
        { key: 'logins', label: '登录记录', children: <LoginHistoryTable rows={logins.data} error={logins.error} onRetry={() => logins.reload()} /> },
      ] : []}
    />
  )
}
