import { batchAction, del, get, post, put, type Page, type PageQuery } from './core'

// ===== 技能（docs/17 §4）=====
// 技能是「操作手册」型知识：模板是人设（保存时渲染进 system_prompt），技能只在模型需要时
// 由内置工具 load_skill(name) 取正文，所以列表不下发正文、详情才有。
// 与提示词模板同一口径：name / description / content 变化才升版本，改完立刻对线上生效（技能不进发布快照）。

// 技能附带资源（首版只存文本；type 字段留给 P2.6 接沙箱后的文件型资源）
export interface SkillResource {
  name: string
  type: string
  content: string
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
  /** 列表不下发，详情 / 保存响应才有 */
  content?: string
}

/** 创建 / 更新请求体（PUT 是整体覆盖，字段缺一个就会被服务端拒或清空） */
export interface SkillInput {
  name: string
  display_name: string
  description: string
  content: string
  resources: SkillResource[]
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
