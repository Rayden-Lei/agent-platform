import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import { Info, RefreshCw, RotateCcw, Save, Settings } from 'lucide-react'
import { Input } from '@/components/shadcn/input'
import { Skeleton } from '@/components/shadcn/skeleton'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/shadcn/tooltip'
import { getSystemSettings, updateSystemSettings, type SystemSettingItem } from '../api'
import { useAsyncData } from '../hooks/useAsyncData'
import { useAuth } from '../store/auth'
import { useUnsaved } from '../store/unsaved'
import PageHeader from '../components/layout/PageHeader'
import ErrorState from '../components/common/ErrorState'
import Button from '../components/ui/Button'
import Badge from '../components/ui/Badge'
import InlineConfirm from '../components/ui/InlineConfirm'
import { errorText } from '../utils/errors'

// 系统参数：导入与检索的调优项在页面上改、立刻生效（docs/04 4.14）。
// 草稿态与已保存值分开：改动先落 draft，点保存才提交；null 表示"恢复默认"（删掉库里的覆盖，回到 .env）。
// 连接类配置（模型地址、密钥）不在这里 —— 属于部署环境，密钥也不能放在能读回的接口上。
type Draft = Record<string, number | null>

// 参数一行：标签行（含来源 / 待保存徽章）、数值输入 + 范围说明、参数用途说明
function SettingRow({ item, draft, canEdit, onEdit }: {
  item: SystemSettingItem
  draft: Draft
  canEdit: boolean
  onEdit: (item: SystemSettingItem, value: number | null) => void
}) {
  const pending = item.key in draft
  const value = pending ? draft[item.key] : item.value
  const shown = value === null ? item.default : value
  const clamp = () => {
    const next = Math.min(item.max, Math.max(item.min, shown))
    if (next !== shown) onEdit(item, next)
  }
  return (
    <div className="flex flex-col gap-1.5 border-b border-border px-4 py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[13.5px] font-medium text-foreground">{item.label}</span>
        {item.source === 'db' && !pending && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span><Badge tone="info">已调整</Badge></span>
            </TooltipTrigger>
            <TooltipContent>{`${item.updated_by || '未知'} 于 ${item.updated_at?.slice(0, 19).replace('T', ' ')} 改的，默认值 ${item.default}`}</TooltipContent>
          </Tooltip>
        )}
        {pending && <Badge tone="warning">{draft[item.key] === null ? '待恢复默认' : '待保存'}</Badge>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Input
          type="number"
          value={String(shown)}
          min={item.min}
          max={item.max}
          step={item.step}
          disabled={!canEdit}
          aria-label={item.label}
          className="h-9 w-[140px]"
          onChange={(e) => onEdit(item, e.target.value === '' ? item.value : Number(e.target.value))}
          onBlur={clamp}
        />
        {item.unit && <span className="text-[12.5px] text-muted-foreground">{item.unit}</span>}
        <span className="text-[12px] text-muted-foreground">范围 {item.min}～{item.max}，默认 {item.default}</span>
        {canEdit && (item.source === 'db' || pending) && (
          <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => onEdit(item, null)}>恢复默认</Button>
        )}
      </div>

      <span className="text-[12px] leading-relaxed text-muted-foreground">{item.description}</span>
    </div>
  )
}

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
      toast.success('已保存，导入参数对下一篇文档生效，检索参数几秒内生效')
      setDraft({})
      reload(true)
    } catch (e) { toast.error(errorText(e, '保存失败')) } finally { setSaving(false) }
  }

  const header = (
    <PageHeader
      title="系统参数"
      icon={<Settings />}
      description="导入与检索的调优参数，改完立刻生效，不用改配置文件重启后端。模型地址与密钥仍在服务端配置文件里。"
      extra={(
        <>
          <Button variant="secondary" size="md" icon={<RefreshCw />} disabled={loading} onClick={() => reload()}>
            {loading ? '刷新中…' : '刷新'}
          </Button>
          {canEdit && (
            <InlineConfirm message={`保存 ${changed.length} 项修改？`} onConfirm={save} confirmLabel="保存">
              <Button variant="primary" size="md" icon={<Save />} disabled={changed.length === 0 || saving}>
                保存{changed.length > 0 ? ` (${changed.length})` : ''}
              </Button>
            </InlineConfirm>
          )}
        </>
      )}
    />
  )

  const body = () => {
    if (loading && !data) {
      return (
        <div className="flex flex-col gap-3">
          {[0, 1].map((i) => (
            <div key={i} className="flex flex-col gap-2.5 rounded-xl border border-border bg-card p-4">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
            </div>
          ))}
        </div>
      )
    }
    if (error && !data) return <ErrorState message={error} onRetry={() => reload()} />
    if (!data) return null
    return (
      <div className="flex flex-col gap-3">
        {!canEdit && (
          <div className="flex items-start gap-2 rounded-lg border border-border bg-secondary px-3 py-2">
            <Info className="mt-0.5 size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
            <p className="m-0 text-[13.5px] text-foreground">只有管理员能修改参数，当前为只读</p>
          </div>
        )}
        {data.groups.map((group) => (
          <section key={group.key} className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
              <h3 className="m-0 text-[13.5px] font-semibold text-foreground">{group.label}</h3>
              <span className="text-[12px] text-muted-foreground">{group.description}</span>
            </div>
            <div>
              {data.items.filter((i) => i.group === group.key).map((item) => (
                <SettingRow key={item.key} item={item} draft={draft} canEdit={canEdit} onEdit={edit} />
              ))}
            </div>
          </section>
        ))}
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      <div className="shrink-0">{header}</div>
      {/* 只有这一段滚动：页头钉死（docs/07 第 1 节） */}
      <div className="min-h-0 flex-1 overflow-auto">{body()}</div>
    </div>
  )
}
