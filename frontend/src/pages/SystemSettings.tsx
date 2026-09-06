import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, InputNumber, Popconfirm, Skeleton, Space, Tag, Tooltip, Typography, message } from 'antd'
import { ReloadOutlined, SaveOutlined, SettingOutlined, UndoOutlined } from '@ant-design/icons'
import { getSystemSettings, updateSystemSettings, type SystemSettingItem } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useAuth } from '../store/auth'
import { useUnsaved } from '../store/unsaved'
import PageHeader from '../components/layout/PageHeader'
import ErrorState from '../components/common/ErrorState'
import { errorText } from '../utils/errors'

// 系统参数：导入与检索的调优项在页面上改、立刻生效（docs/04 4.14）。
// 草稿态与已保存值分开：改动先落 draft，点保存才提交；null 表示"恢复默认"（删掉库里的覆盖，回到 .env）。
// 连接类配置（模型地址、密钥）不在这里 —— 属于部署环境，密钥也不能放在能读回的接口上。
type Draft = Record<string, number | null>

export default function SystemSettings() {
  const role = useAuth((s) => s.user?.role)
  const canEdit = role === 'admin'
  const setDirty = useUnsaved((s) => s.setDirty)
  const { data, loading, error, reload } = useAsyncData(getSystemSettings, [], { errorText: '参数加载失败' })
  const [draft, setDraft] = useState<Draft>({})
  const [saving, setSaving] = useState(false)

  // 草稿里只留"和当前生效值不同"的项：改回原值等于没改，保存按钮也该恢复禁用
  const changed = useMemo(() => Object.keys(draft), [draft])
  useEffect(() => { setDirty(changed.length > 0); return () => setDirty(false) }, [changed.length, setDirty])

  const edit = (item: SystemSettingItem, value: number | null) => {
    setDraft((prev) => {
      const next = { ...prev }
      const restoring = value === null
      // 恢复默认：只有当前确实来自库里的覆盖才算改动
      if ((restoring && item.source === 'default') || (!restoring && value === item.value)) delete next[item.key]
      else next[item.key] = value
      return next
    })
  }

  const save = async () => {
    setSaving(true)
    try {
      await updateSystemSettings(draft)
      message.success('已保存，导入参数对下一篇文档生效，检索参数几秒内生效')
      setDraft({})
      reload(true)
    } catch (e) { message.error(errorText(e, '保存失败')) } finally { setSaving(false) }
  }

  const header = (
    <PageHeader
      title="系统参数"
      icon={<SettingOutlined />}
      description="导入与检索的调优参数，改完立刻生效，不用改配置文件重启后端。模型地址与密钥仍在服务端配置文件里。"
      extra={(
        <Space>
          <Button icon={<ReloadOutlined />} onClick={() => reload()} loading={loading}>刷新</Button>
          {canEdit && (
            <Popconfirm title={`保存 ${changed.length} 项修改？`} onConfirm={save} disabled={changed.length === 0}>
              <Button type="primary" icon={<SaveOutlined />} disabled={changed.length === 0} loading={saving}>
                保存{changed.length > 0 ? ` (${changed.length})` : ''}
              </Button>
            </Popconfirm>
          )}
        </Space>
      )}
    />
  )

  const body = () => {
    if (loading && !data) return <Skeleton active paragraph={{ rows: 10 }} />
    if (error && !data) return <ErrorState message={error} onRetry={() => reload()} />
    if (!data) return null
    return (
      <Space direction="vertical" size={12} style={{ width: '100%' }}>
        {!canEdit && <Alert type="info" showIcon message="只有管理员能修改参数，当前为只读" />}
        {data.groups.map((group) => (
          <Card key={group.key} size="small" title={group.label} extra={<Typography.Text type="secondary" style={{ fontSize: 12 }}>{group.description}</Typography.Text>}>
            <Descriptions column={1} size="small" bordered items={data.items.filter((i) => i.group === group.key).map((item) => {
              const pending = item.key in draft
              const value = pending ? draft[item.key] : item.value
              const shown = value === null ? item.default : value
              return {
                key: item.key,
                label: (
                  <Space size={6}>
                    <span>{item.label}</span>
                    {item.source === 'db' && !pending && <Tooltip title={`${item.updated_by || '未知'} 于 ${item.updated_at?.slice(0, 19).replace('T', ' ')} 改的，默认值 ${item.default}`}><Tag color="blue">已调整</Tag></Tooltip>}
                    {pending && <Tag color="orange">{draft[item.key] === null ? '待恢复默认' : '待保存'}</Tag>}
                  </Space>
                ),
                children: (
                  <Space direction="vertical" size={4} style={{ width: '100%' }}>
                    <Space wrap>
                      <InputNumber
                        value={shown}
                        min={item.min}
                        max={item.max}
                        step={item.step}
                        disabled={!canEdit}
                        style={{ width: 140 }}
                        addonAfter={item.unit || undefined}
                        onChange={(v) => edit(item, typeof v === 'number' ? v : item.value)}
                      />
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        范围 {item.min}～{item.max}，默认 {item.default}
                      </Typography.Text>
                      {canEdit && (item.source === 'db' || pending) && (
                        <Button size="small" type="link" icon={<UndoOutlined />} onClick={() => edit(item, null)}>恢复默认</Button>
                      )}
                    </Space>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>{item.description}</Typography.Text>
                  </Space>
                ),
              }
            })} />
          </Card>
        ))}
      </Space>
    )
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ flexShrink: 0 }}>{header}</div>
      {/* 只有这一段滚动：页头钉死（docs/07 第 1 节） */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>{body()}</div>
    </div>
  )
}
