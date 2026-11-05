import { useRef, useState } from 'react'
import { toast } from 'sonner'
import { Upload } from 'lucide-react'
import Modal from '../ui/Modal'
import Button from '../ui/Button'
import { parseSkillMd, type ParsedSkill } from '../../api'
import { errorText } from '../../utils/errors'

// 导入 SKILL.md（Agent Skills 开放标准，GitHub 上下载的技能就是这个格式）。
// 只解析不落库：解析出的字段交给外层填进编辑弹窗，使用者确认后走正常的保存接口 ——
// 导入与手填共用同一条校验路径，不存在「导入能绕过 name 格式、正文上限」的第二套入口。
interface Props {
  open: boolean
  onClose: () => void
  /** 解析成功：把字段交给编辑弹窗（新建态），由使用者确认后保存 */
  onParsed: (parsed: ParsedSkill) => void
}

const MAX_BYTES = 64 * 1024
const kbText = (bytes: number) => (bytes / 1024).toFixed(1) + 'KB'

export default function SkillImportModal({ open, onClose, onParsed }: Props) {
  const [text, setText] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [parsing, setParsing] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const reset = () => { setText(''); setFileName(null); setError(null); setParsing(false) }
  const close = () => { reset(); onClose() }

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

  const onParse = async () => {
    if (!text.trim()) { setError('请先选择 SKILL.md 文件或粘贴内容'); return }
    setParsing(true)
    try {
      const parsed = await parseSkillMd(text)
      toast.success('已解析：' + parsed.display_name)
      reset()
      onParsed(parsed)
    } catch (e) {
      // 400 的 detail 已写明哪里不对（缺 frontmatter / 缺 name / 不支持的 YAML），原样上屏
      setError(errorText(e, '解析失败'))
    } finally {
      setParsing(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={close}
      size="lg"
      title="导入 SKILL.md"
      description="支持 Agent Skills 开放标准（agentskills.io）的 SKILL.md，GitHub 上多数技能仓库都是这个格式"
      footer={(
        <>
          <Button variant="ghost" size="md" onClick={close}>取消</Button>
          <Button variant="primary" size="md" disabled={parsing || !text.trim()} onClick={onParse}>
            {parsing ? '解析中…' : '解析并填入'}
          </Button>
        </>
      )}
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <input ref={fileRef} type="file" accept=".md,text/markdown" className="hidden" onChange={(e) => onPick(e.target.files)} />
          <Button size="sm" variant="secondary" icon={<Upload className="size-3.5" />} onClick={() => fileRef.current?.click()}>
            选择 SKILL.md 文件
          </Button>
          {fileName && <span className="truncate text-[12.5px] text-muted-foreground">{fileName}</span>}
        </div>

        <textarea
          rows={14}
          value={text}
          onChange={(e) => { setText(e.target.value); setFileName(null); setError(null) }}
          placeholder={'---\nname: pdf-processing\ndescription: 处理 PDF 时使用\n---\n\n正文…'}
          className="w-full resize-y rounded-lg border border-input bg-transparent px-3 py-2 font-mono text-[13px] leading-relaxed outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />

        <p className="m-0 text-[12px] text-muted-foreground">
          文件开头的 <code className="font-mono">---</code> 之间是 frontmatter，必须有 <code className="font-mono">name</code> 与
          <code className="font-mono"> description</code>。解析结果会填进新增弹窗，确认后再保存；这里不会写库。
          技能附带的 scripts / references 目录需要单独上传（保存后在编辑弹窗里上传脚本）。
        </p>

        {error && <p className="m-0 text-[12.5px] text-destructive">{error}</p>}
      </div>
    </Modal>
  )
}
