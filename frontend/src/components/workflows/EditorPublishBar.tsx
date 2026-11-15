import { Rocket, Save } from 'lucide-react'
import Button from '../ui/Button'

// 编辑器头部的"发布状态 + 发布/保存"按钮组（FR-075）。
// 抽成组件是为了让 WorkflowEditor 只保留画布逻辑：这里的三段状态与两个按钮要一起改，
// 散落在编辑器的 header JSX 里最容易出现"改了提示忘了改按钮禁用态"。
interface Props {
  isNew: boolean
  publishedVersion: number | null // 线上版本号；从未发布为 null
  hasUnpublished: boolean // 草稿与线上不一致
  saving: boolean
  publishing: boolean
  testing: boolean
  onPublish: () => void
  onSave: () => void
}

export default function EditorPublishBar({ isNew, publishedVersion, hasUnpublished, saving, publishing, testing, onPublish, onSave }: Props) {
  return (
    <div className="flex shrink-0 items-center gap-2">
      {/* 「有未发布改动」提示：保存只改草稿，发布才对外生效。没有这个提示，用户会以为
          "保存成功"就意味着定时任务与 API 调用已经用上新图（这个特性之前确实是保存即上线）。 */}
      {!isNew && hasUnpublished && (
        <span
          className="hidden items-center gap-1.5 rounded-lg border border-border bg-secondary px-2.5 py-1 text-[12px] text-foreground sm:inline-flex"
          title="草稿的改动还没对外生效；线上的定时任务与 API 调用仍在跑旧版本"
        >
          <span className="size-1.5 rounded-full" style={{ background: 'var(--warning, #d97706)' }} />
          有未发布改动
        </span>
      )}
      {!isNew && publishedVersion === null && (
        <span className="hidden items-center gap-1.5 rounded-lg border border-border bg-secondary px-2.5 py-1 text-[12px] text-muted-foreground sm:inline-flex">
          尚未发布，不能运行
        </span>
      )}
      <Button variant="secondary" size="md" icon={<Rocket />} disabled={saving || publishing || testing} onClick={onPublish}>
        {publishing ? '发布中…' : '发布'}
      </Button>
      <Button variant="primary" size="md" icon={<Save />} disabled={saving || testing || publishing} onClick={onSave}>
        {saving ? '保存中…' : '保存'}
      </Button>
    </div>
  )
}
