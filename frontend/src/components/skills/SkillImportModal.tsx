import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { Link2, Upload, Loader2, AlertTriangle, FileCode2 } from 'lucide-react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { Input } from '@/components/shadcn/input'
import {
  parseSkillMd, previewSkillFromGitHub,
  type GitHubImportPreview, type ParsedSkill,
} from '../../api'
import { errorText } from '../../utils/errors'

// 导入技能。两个入口，主次分明：
//
// **主入口：贴 GitHub 地址**。技能生态基本都在 GitHub（anthropics/skills、各种 marketplace），
// 贴一个仓库里技能目录的浏览地址就能把 SKILL.md 与它的脚本资源一起拉下来 ——
// 这是这个功能实际会被用一万次的路径。
//
// **兜底：本地文件 / 粘贴**。私有技能、自己写的、网络不通时的退路。
//
// 两者都只解析不落库：结果交给外层填进新建弹窗，使用者确认后才走保存接口。
// 导入与手填共用同一条校验路径，不存在「导入能绕过 name 格式、正文上限」的第二套入口。
interface Props {
  open: boolean
  onClose: () => void
  /** 解析成功：把字段交给编辑弹窗（新建态），由使用者确认后保存 */
  onParsed: (parsed: ParsedSkill | GitHubImportPreview) => void
}

const MAX_BYTES = 64 * 1024
const kbText = (bytes: number) => (bytes / 1024).toFixed(1) + 'KB'

type Tab = 'github' | 'file'

export default function SkillImportModal({ open, onClose, onParsed }: Props) {
  const [tab, setTab] = useState<Tab>('github')
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const reset = () => { setUrl(''); setText(''); setFileName(null); setError(null); setBusy(false) }
  const close = () => { reset(); onClose() }
  const switchTab = (t: Tab) => { setTab(t); setError(null) }

  const onPick = async (files: FileList | null) => {
    const file = files?.[0]
    if (!file) return
    // 正文上限按 UTF-8 字节算（服务端同样校验）；先看 file.size 省掉读进内存
    if (file.size > MAX_BYTES) {
      setError('文件 ' + kbText(file.size) + '，超过 64KB 上限，先拆成多个技能')
      return
    }
    try {
      setText(await file.text())
      setFileName(file.name)
      setError(null)
    } catch (e) {
      setError(errorText(e, '读取文件失败'))
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const fromGitHub = async () => {
    const u = url.trim()
    if (!u) { setError('请粘贴 GitHub 地址'); return }
    setBusy(true)
    setError(null)
    try {
      const preview = await previewSkillFromGitHub(u)
      const extra = preview.files.length ? `，带 ${preview.files.length} 个资源` : ''
      toast.success('已读取 ' + preview.repo + extra)
      reset()
      onParsed(preview)
    } catch (e) {
      setError(errorText(e, '读取 GitHub 失败'))
    } finally {
      setBusy(false)
    }
  }

  const fromText = async () => {
    if (!text.trim()) { setError('请先选择 SKILL.md 文件或粘贴内容'); return }
    setBusy(true)
    setError(null)
    try {
      const parsed = await parseSkillMd(text)
      toast.success('已解析：' + parsed.display_name)
      reset()
      onParsed(parsed)
    } catch (e) {
      // 400 的 detail 已写明哪里不对（缺 frontmatter / 缺 name / 不支持的 YAML），原样上屏
      setError(errorText(e, '解析失败'))
    } finally {
      setBusy(false)
    }
  }

  const canSubmit = tab === 'github' ? !!url.trim() : !!text.trim()

  return (
    <Modal
      open={open}
      onClose={close}
      size="lg"
      title="导入技能"
      description="贴一个 GitHub 地址即可：会把 SKILL.md 与它附带的脚本资源一起读取"
      footer={(
        <>
          <Button variant="ghost" size="md" onClick={close}>取消</Button>
          <Button
            variant="primary" size="md" disabled={busy || !canSubmit}
            icon={busy ? <Loader2 className="size-3.5 animate-spin" /> : undefined}
            onClick={tab === 'github' ? fromGitHub : fromText}
          >
            {busy ? '读取中…' : tab === 'github' ? '从 GitHub 读取' : '解析并填入'}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-4">
        {/* 两个入口用分段控件，默认停在 GitHub —— 那是绝大多数人的来意 */}
        <div className="flex gap-1 rounded-lg bg-muted p-1">
          {([
            { key: 'github' as Tab, label: '从 GitHub 导入', icon: <Link2 className="size-3.5" /> },
            { key: 'file' as Tab, label: '本地文件 / 粘贴', icon: <FileCode2 className="size-3.5" /> },
          ]).map(({ key, label, icon }) => (
            <button
              key={key}
              type="button"
              onClick={() => switchTab(key)}
              className={`flex flex-1 items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] transition-colors ${
                tab === key ? 'bg-background text-foreground shadow-sm' : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              {icon}{label}
            </button>
          ))}
        </div>

        {tab === 'github' ? (
          <>
            <div className="flex flex-col gap-1.5">
              <Input
                value={url}
                onChange={(e) => { setUrl(e.target.value); setError(null) }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !busy && url.trim()) fromGitHub() }}
                placeholder="https://github.com/anthropics/skills/tree/main/skills/pdf"
                spellCheck={false}
                autoFocus
              />
              <p className="m-0 text-[12px] leading-relaxed text-muted-foreground">
                把仓库里技能目录的<strong className="font-medium text-foreground">浏览器地址</strong>直接粘过来。
                只支持 github.com；私有仓库暂不支持。
              </p>
            </div>

            <div className="rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-[12px] leading-relaxed text-muted-foreground">
              <div className="mb-1 font-medium text-foreground">地址怎么找</div>
              <ol className="m-0 list-decimal space-y-0.5 pl-4">
                <li>在 GitHub 上打开技能目录（里面有一个 <code className="font-mono">SKILL.md</code>）</li>
                <li>复制浏览器地址栏的地址，形如 <code className="font-mono">.../tree/main/skills/pdf</code></li>
                <li>粘到上面，点「从 GitHub 读取」</li>
              </ol>
              <div className="mt-1.5">
                只贴仓库根（<code className="font-mono">.../owner/repo</code>）也行：只有一处技能时会自动找到它；
                有多个时会列出来让你选具体哪个。
              </div>
            </div>

            <p className="m-0 text-[12px] text-muted-foreground">
              读取到的是<b className="font-medium text-foreground">预览</b>：会先确认技能字段，确认后才真正创建；
              附带的 <code className="font-mono">.py</code> / <code className="font-mono">.md</code> 等文本资源会一起导入，
              图片与压缩包会跳过并告诉你跳过了哪些。
            </p>
          </>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <input ref={fileRef} type="file" accept=".md,text/markdown" className="hidden" onChange={(e) => onPick(e.target.files)} />
              <Button size="sm" variant="secondary" icon={<Upload className="size-3.5" />} onClick={() => fileRef.current?.click()}>
                选择 SKILL.md 文件
              </Button>
              {fileName && <span className="truncate text-[12.5px] text-muted-foreground">{fileName}</span>}
            </div>

            <textarea
              rows={12}
              value={text}
              onChange={(e) => { setText(e.target.value); setFileName(null); setError(null) }}
              placeholder={'---\nname: pdf-processing\ndescription: 处理 PDF 时使用\n---\n\n正文…'}
              className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
            />

            <p className="m-0 text-[12px] text-muted-foreground">
              文件开头的 <code className="font-mono">---</code> 之间是 frontmatter，必须有 <code className="font-mono">name</code> 与
              <code className="font-mono"> description</code>。这条路<b className="font-medium text-foreground">不会带上脚本资源</b>，
              需要保存后在编辑弹窗里单独上传 —— 要连资源一起导入，用「从 GitHub 导入」。
            </p>
          </>
        )}

        {error && (
          <div className="flex items-start gap-1.5 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
            <p className="m-0 text-[12.5px] leading-relaxed text-destructive">{error}</p>
          </div>
        )}
      </div>
    </Modal>
  )
}
