import type { ReactNode } from 'react'
import { ArrowLeft } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Skeleton } from '@/components/shadcn/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/shadcn/tabs'
import ErrorState from '../common/ErrorState'
import Button from '../ui/Button'
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
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="detail-header shrink-0">
        <PageHeader
          crumbs={crumbs}
          title={loading ? <Skeleton className="h-6 w-48" /> : title}
          tags={tags}
          extra={
            <>
              {extra}
              <Button variant="secondary" size="md" icon={<ArrowLeft />} onClick={back}>返回</Button>
            </>
          }
        />
        {meta && meta.length > 0 && !loading && (
          <dl className="m-0 mt-3 grid grid-cols-1 gap-x-5 gap-y-2 sm:grid-cols-2 md:grid-cols-4">
            {meta.map((m, i) => (
              <div key={i} className="min-w-0">
                <dt className="text-[12px] text-muted-foreground">{m.label}</dt>
                <dd className="m-0 truncate text-[13.5px] text-foreground">{m.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>

      {error ? (
        <ErrorState message={error} onRetry={onRetry} />
      ) : (
        <Tabs value={activeKey} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col gap-3">
          <TabsList className="shrink-0 justify-start">
            {tabs.map((t) => <TabsTrigger key={t.key} value={t.key} className="flex-none px-3">{t.label}</TabsTrigger>)}
          </TabsList>
          {tabs.map((t) => (
            <TabsContent key={t.key} value={t.key} className="detail-tab-body min-h-0 flex-1 overflow-auto">
              {t.children}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  )
}
