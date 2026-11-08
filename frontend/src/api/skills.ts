import client from './client'
import { batchAction, del, get, post, put, type OkResponse, type Page, type PageQuery } from './core'

// ===== 技能（docs/17 §4）=====
// 技能是「操作手册」型知识：模板是人设（保存时渲染进 system_prompt），技能只在模型需要时
// 由内置工具 load_skill(name) 取正文，所以列表不下发正文、详情才有。
// 与提示词模板同一口径：name / description / content 变化才升版本，改完立刻对线上生效（技能不进发布快照）。

// 技能附带资源（docs/17 §4.5）：两类，界面都按「文件」展示
//   {type:'text', content}                              内联文本，直接进库
//   {type:'file', object:'skills/3/add.py', size}       文件型，正文在对象存储
// 资源只能走 /skills/{id}/resources 子接口增删，保存技能不会动它们（SkillInput 里没有 resources）。
export interface SkillResource {
  name: string
  type: 'text' | 'file' | string
  content?: string
  /** 对象存储键，文件型才有 */
  object?: string
  /** 文件型为对象实际字节数；内联文本为 content 的 UTF-8 字节数 */
  size?: number | null
  /** 文件型的对象在桶里找不到了（被外部删掉），列表要标出来 */
  missing?: boolean
}

export interface SkillRow {
  id: number
  /** 模型 load_skill 时唯一能传的标识：小写字母数字与连字符（^[a-z0-9]+(-[a-z0-9]+)*$） */
  name: string
  display_name: string
  /** 决定模型会不会用这个技能，必填 */
  description: string
  /** 常驻：正文每轮都拼进系统提示；否则只把 name + description 放进「可用技能」目录 */
  always_on: boolean
  is_enabled: boolean
  version: number
  resources: SkillResource[]
  created_by: number | null
  created_by_username?: string | null
  created_at: string | null
  updated_at: string | null
  /** 列表附带：绑定该技能的智能体数 */
  agents_count?: number
  /** 详情附带：绑定该技能的智能体清单（删不掉时「仍有 N 个绑定」得知道是哪几个） */
  agents?: { id: number; name: string; status: string }[]
  /** 列表不下发，详情 / 保存响应才有 */
  content?: string
}

/** 创建 / 更新请求体（PUT 是整体覆盖，字段缺一个就会被服务端拒或清空）。
 *  不含 resources：资源由 listSkillResources / uploadSkillResource / deleteSkillResource 单独管理，
 *  多传 resources 服务端会 422（extra=forbid）。 */
export interface SkillInput {
  name: string
  display_name: string
  description: string
  content: string
  always_on: boolean
  is_enabled: boolean
}

/** 列表页头部：技能总数与启用数 */
export interface SkillStats {
  total: number
  enabled: number
}

export const listSkills = (params?: PageQuery) => get<Page<SkillRow>>('/skills', params)
export const getSkill = (id: number) => get<SkillRow>(`/skills/${id}`)
// 重名 409「技能名称已存在」；正文按 UTF-8 字节超 64KB 400
export const createSkill = (data: SkillInput) => post<SkillRow>('/skills', data)
export const updateSkill = (id: number, data: SkillInput) => put<SkillRow>(`/skills/${id}`, data)
// 仍被智能体绑定 409（skill_ids 是 JSONB 无外键，先解绑再删）
export const deleteSkill = (id: number) => del(`/skills/${id}`)
export const batchSkills = (ids: number[]) => batchAction('/skills', ids, 'delete')
export const getSkillStats = () => get<SkillStats>('/skills/stats')

/** 解析 SKILL.md 的返回：技能字段 + 原样保留的可选元信息（不落库） */
export interface ParsedSkill {
  name: string
  display_name: string
  description: string
  content: string
  always_on: boolean
  is_enabled: boolean
  resources: SkillResource[]
  /** license / compatibility / allowed-tools / metadata，原样来自 frontmatter */
  meta: Record<string, unknown>
}

// 解析 GitHub 上下载的 SKILL.md（Agent Skills 开放标准）：只解析不落库，字段回给编辑弹窗，
// 使用者确认后走正常的 createSkill —— 导入与手填共用同一条校验路径
export const parseSkillMd = (text: string) => post<ParsedSkill>('/skills/parse', { text })

// ===== 从 GitHub 导入（2026-11-08）=====
// 贴仓库里技能目录的浏览地址，服务端拉 SKILL.md 与它的资源。分两步：
// 先预览（不落库，使用者确认字段），再 commit。
// 只支持 github.com 的浏览地址：服务端限定域名，不开放任意 URL 抓取（SSRF）。
export interface GitHubImportPreview extends ParsedSkill {
  /** 预览时用的原始地址：确认导入时要原样回传（服务端据此重新抓取） */
  url: string
  /** owner/repo */
  repo: string
  /** 实际用的分支：地址里没写就是仓库默认分支 */
  ref: string
  /** 技能目录在仓库里的路径 */
  dir_path: string
  /** 会一起导入的资源（只有名字与大小，内容在服务端） */
  files: { name: string; size: number }[]
  /** 被跳过的文件及原因（非文本类型、超大、超数量上限） */
  skipped: string[]
}

/** 确认导入的请求体：技能字段由使用者确认后带回，**正文以服务端重新抓取为准** */
export interface GitHubImportCommit {
  url: string
  name: string
  display_name: string
  description: string
  always_on: boolean
  is_enabled: boolean
}

export interface GitHubImportResult extends SkillRow {
  imported: {
    repo: string
    ref: string
    dir_path: string
    files: string[]
    skipped: string[]
  }
}

export const previewSkillFromGitHub = (url: string) =>
  post<GitHubImportPreview>('/skills/import-github', { url }, { timeout: 60000 })

export const commitSkillFromGitHub = (data: GitHubImportCommit) =>
  post<GitHubImportResult>('/skills/import-github/commit', data, { timeout: 120000 })

// ===== 技能资源（docs/04 §4.20）=====
// 首版只收 .py：沙箱按 python 起进程，别的语言需要另一套加固。单个上限 512KB（服务端 413）。
// 上传走 FormData，与知识库文档上传同一写法（axios 自动带 multipart 头，不设超时）
export const SKILL_RESOURCE_SUFFIXES = ['.py']
export const SKILL_RESOURCE_MAX_BYTES = 512 * 1024

/** 资源清单：文件型带 size 与实际对象状态（missing 表示对象已不在桶里） */
export const listSkillResources = (id: number) => get<SkillResource[]>('/skills/' + id + '/resources')
// 同名上传是覆盖（改脚本就是这个动作）；名字允许单层目录，如 scripts/add.py
export const uploadSkillResource = (id: number, file: File, onProgress?: (percent: number) => void) => {
  const fd = new FormData()
  fd.append('file', file)
  return client.post('/skills/' + id + '/resources', fd, {
    timeout: 0,
    onUploadProgress: (e) => { if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100)) },
  }) as unknown as Promise<SkillResource>
}
// 资源名带目录时路径里含 /，服务端用 {name:path} 接；这里按段编码，不整体 encodeURIComponent（那样 / 会变成 %2F 匹配不上）
export const deleteSkillResource = (id: number, name: string) =>
  del<OkResponse>('/skills/' + id + '/resources/' + name.split('/').map(encodeURIComponent).join('/'))

/** 技能对模型长什么样（纯本地拼装，不调模型、不花 token） */
export interface SkillPreview {
  id: number
  name: string
  is_enabled: boolean
  always_on: boolean
  /** 非常驻技能：这一行进「可用技能」目录，模型据此决定要不要加载 */
  in_catalog: boolean
  catalog_line: string
  /** 常驻技能：这段正文每轮都拼进系统提示 */
  always_on_body: string
  /** 模型真调 load_skill 时拿到的完整返回 */
  load_skill_result: string
  tokens: { catalog: number; always_on_body: number; load_skill_result: number }
  /** 每轮固定开销：常驻=正文，按需=目录那一行 */
  per_turn_overhead: number
  content_bytes: number
  /** 按常见写错法给的提示，只提示不阻断 */
  advice: string[]
}

// 预览「模型眼里的这个技能」：哪段会进提示词、多少 token、有什么坑。
// 这条把反馈回路从"绑到智能体跑一轮"缩短到"点一下"——技能写错最贵的是试错成本
export const previewSkill = (id: number) => get<SkillPreview>('/skills/' + id + '/preview')
