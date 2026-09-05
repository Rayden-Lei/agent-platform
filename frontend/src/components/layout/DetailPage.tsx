import type { ReactNode } from 'react'
import { Button, Descriptions, Skeleton, Space, Tabs } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import ErrorState from '../common/ErrorState'
import PageHeader, { type Crumb } from './PageHeader'

// 详情页骨架：面包屑 / 标题 / 标签 / 关键信息一行 / 操作区 + 页签；页签面板是唯一滚动区；?tab= 深链。
export interface DetailTab { key: string; label: ReactNode; children: ReactNode }
interface Props {
  crumbs: Crumb[]
  title: ReactNode
  tags?: ReactNode
  meta?: { label: ReactNode; value: ReactNode }[]
  extra?: ReactNode
  tabs: DetailTab[]
  defaultTab?: string
  loading?: boolean
  error?: string | null
  onRetry?: () => void
  backTo: string
}

export default function DetailPage({ crumbs, title, tags, meta, extra, tabs, defaultTab, loading, error, onRetry, backTo }: Props) {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const activeKey = params.get('tab') || defaultTab || tabs[0]?.key
  const back = () => (window.history.length > 1 ? navigate(-1) : navigate(backTo))
  const setTab = (key: string) => {
    const next = new URLSearchParams(params)
    if (key === (defaultTab || tabs[0]?.key)) next.delete('tab')
    else next.set('tab', key)
    setParams(next, { replace: true })
  }

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div className="detail-header" style={{ flexShrink: 0 }}>
        <PageHeader
          crumbs={crumbs}
          title={loading ? <Skeleton.Input active size="small" style={{ width: 200 }} /> : title}
          tags={tags}
          extra={<Space>{extra}<Button icon={<ArrowLeftOutlined />} onClick={back}>返回</Button></Space>}
        />
        {meta && meta.length > 0 && !loading && (
          <Descriptions size="small" column={{ xs: 1, sm: 2, md: 4 }} items={meta.map((m, i) => ({ key: String(i), label: m.label, children: m.value }))} style={{ marginTop: 8 }} />
        )}
      </div>
      {error ? (
        <ErrorState message={error} onRetry={onRetry} />
      ) : (
        <Tabs
          activeKey={activeKey}
          onChange={setTab}
          items={tabs.map((t) => ({ key: t.key, label: t.label, children: <div className="detail-tab-body">{t.children}</div> }))}
          className="detail-tabs"
        />
      )}
    </div>
  )
}
