import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { FileCode2, Upload, X } from 'lucide-react'
import Button from '../ui/Button'
import InlineConfirm from '../ui/InlineConfirm'
import Badge from '../ui/Badge'
import {
  deleteSkillResource, listSkillResources, uploadSkillResource,
  SKILL_RESOURCE_MAX_BYTES, SKILL_RESOURCE_SUFFIXES, type SkillResource,
} from '../../api'
import { errorText } from '../../utils/errors'

// 技能资源（docs/17 §4.5）：.py 脚本进对象存储，模型调 run_skill_script 时在沙箱里执行。
// 只在**已保存**的技能上出现 —— 资源挂在 /skills/{id}/resources 下，新建时还没有 id。
// 资源不进技能正文的 64KB 限额，也不参与版本号：改脚本立刻生效，与技能正文同一口径。
interface Props {
  skillId: number
  /** 上传 / 删除后通知外层刷新详情（资源清单与技能详情是两个接口） */
  onChanged: () => void
}

const kbText = (bytes: number) => (bytes / 1024).toFixed(1) + 'KB'

export default function SkillResources({ skillId, onChanged }: Props) {
  const [items, setItems] = useState<SkillResource[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const reload = async () => {
    setLoading(true)
    try {
      setItems(await listSkillResources(skillId))
      setError(null)
    } catch (e) {
      // 清单拉不到不影响编辑正文，只在这个区块里说明，不打断整个抽屉
      setError(errorText(e, '加载资源失败'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void reload() }, [skillId]) // eslint-disable-line react-hooks/exhaustive-deps

  const onPick = async (files: FileList | null) => {
    if (!files?.length) return
    const file = files[0]
    // 服务端同样校验（400 / 413），这里只是省掉「传完才被拒」
    if (!SKILL_RESOURCE_SUFFIXES.some((s) => file.name.toLowerCase().endsWith(s))) {
      toast.error('首版只支持 ' + SKILL_RESOURCE_SUFFIXES.join(' / ') + ' 资源')
      return
    }
    if (file.size > SKILL_RESOURCE_MAX_BYTES) {
      toast.error('单个资源最多 ' + SKILL_RESOURCE_MAX_BYTES / 1024 + 'KB，这个文件 ' + kbText(file.size))
      return
    }
    setUploading({ name: file.name, percent: 0 })
    try {
      await uploadSkillResource(skillId, file, (percent) => setUploading({ name: file.name, percent }))
      toast.success(file.name + ' 已上传')
      await reload()
      onChanged()
    } catch (e) {
      toast.error(errorText(e, file.name + ' 上传失败'))
    } finally {
      setUploading(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const onDelete = async (name: string) => {
    try {
      await deleteSkillResource(skillId, name)
      toast.success('已删除')
      await reload()
      onChanged()
    } catch (e) {
      toast.error(errorText(e, '删除失败'))
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <span className="text-[13px] font-medium">脚本资源</span>
          <p className="m-0 mt-0.5 text-[12px] text-muted-foreground">
            上传后模型可调 <code className="font-mono">run_skill_script</code> 在沙箱里执行；改完立刻生效，不影响技能版本号。
            首版只收 {SKILL_RESOURCE_SUFFIXES.join(' / ')}，单个上限 {SKILL_RESOURCE_MAX_BYTES / 1024}KB。
          </p>
        </div>
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept={SKILL_RESOURCE_SUFFIXES.join(',')}
          onChange={(e) => onPick(e.target.files)}
        />
        <Button
          size="sm"
          variant="secondary"
          icon={<Upload className="size-3.5" />}
          disabled={!!uploading}
          onClick={() => fileRef.current?.click()}
        >
          {uploading ? '上传中 ' + uploading.percent + '%' : '上传脚本'}
        </Button>
      </div>

      {loading && items.length === 0 && <p className="m-0 text-[12px] text-muted-foreground">加载中…</p>}
      {error && <p className="m-0 text-[12px] text-destructive">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <p className="m-0 text-[12px] text-muted-foreground">还没有脚本。没有脚本时模型不会看到执行工具，只按正文操作。</p>
      )}

      {items.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0">
          {items.map((r) => (
            <li key={r.name} className="flex items-center gap-2 rounded-md px-1.5 py-1 hover:bg-accent">
              <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" />
              <code className="min-w-0 flex-1 truncate text-[12.5px]" style={{ fontFamily: '"SF Mono",Consolas,monospace' }}>
                {r.name}
              </code>
              {r.missing ? (
                <Badge tone="danger" title="对象存储里已经找不到这个文件，重新上传即可恢复">文件缺失</Badge>
              ) : (
                <span className="shrink-0 text-[12px] text-muted-foreground">{r.size == null ? '-' : kbText(r.size)}</span>
              )}
              <InlineConfirm message={'删除脚本 ' + r.name + '？模型将无法再执行它'} danger onConfirm={() => onDelete(r.name)}>
                <button
                  type="button"
                  className="rounded p-0.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                  aria-label={'删除 ' + r.name}
                >
                  <X className="size-3.5" />
                </button>
              </InlineConfirm>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
