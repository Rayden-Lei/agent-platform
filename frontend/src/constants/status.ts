// 全站状态字典：中文文案 + 语义色（docs/07 第 6 节：published/success/ready 绿，draft/awaiting_review 橙，
// running/processing 蓝，failed 红）。筛选下拉与标签同源，页面里不许再各写一份映射。
export type StatusDomain =
  | 'run' | 'runType' | 'runSource' | 'agent' | 'workflow' | 'document' | 'enabled' | 'role'
  | 'toolType' | 'auditAction' | 'auditResource' | 'breaker' | 'nodeStatus' | 'provider' | 'visibility'

export interface StatusMeta { label: string; color: string }

export const STATUS: Record<StatusDomain, Record<string, StatusMeta>> = {
  run: {
    running: { label: '运行中', color: 'processing' },
    success: { label: '成功', color: 'success' },
    failed: { label: '失败', color: 'error' },
    cancelled: { label: '已取消', color: 'default' },
    awaiting_review: { label: '待审核', color: 'warning' },
  },
  runType: { chat: { label: '对话', color: 'blue' }, workflow: { label: '工作流', color: 'geekblue' } },
  runSource: {
    chat: { label: '对话', color: 'blue' },
    ui: { label: '界面运行', color: 'default' },
    api_key: { label: 'API Key', color: 'purple' },
    schedule: { label: '定时任务', color: 'cyan' },
  },
  agent: { draft: { label: '草稿', color: 'warning' }, published: { label: '已发布', color: 'success' } },
  workflow: { draft: { label: '草稿', color: 'warning' }, published: { label: '已发布', color: 'success' } },
  document: {
    uploading: { label: '上传中', color: 'processing' },
    parsing: { label: '解析中', color: 'processing' },
    chunking: { label: '切片中', color: 'processing' },
    ready: { label: '就绪', color: 'success' },
    failed: { label: '失败', color: 'error' },
  },
  enabled: { true: { label: '启用', color: 'success' }, false: { label: '停用', color: 'default' } },
  role: { admin: { label: '管理员', color: 'red' }, developer: { label: '开发者', color: 'blue' }, caller: { label: '调用者', color: 'default' } },
  toolType: { builtin: { label: '内置', color: 'blue' }, http: { label: 'HTTP', color: 'green' } },
  auditAction: {
    login: { label: '登录', color: 'green' },
    login_failed: { label: '登录失败', color: 'red' },
    create: { label: '创建', color: 'blue' },
    update: { label: '更新', color: 'orange' },
    delete: { label: '删除', color: 'red' },
    publish: { label: '发布', color: 'orange' },
    rollback: { label: '回滚', color: 'orange' },
    enable: { label: '启用', color: 'green' },
    disable: { label: '停用', color: 'default' },
    reset_password: { label: '重置密码', color: 'volcano' },
    rag_retrieve: { label: '知识检索', color: 'cyan' },
    api_key_ip_rejected: { label: 'Key 来源被拒', color: 'red' },
  },
  auditResource: {
    auth: { label: '登录', color: 'default' },
    model: { label: '模型', color: 'default' },
    agent: { label: '智能体', color: 'default' },
    prompt_template: { label: '提示词模板', color: 'default' },
    user: { label: '用户', color: 'default' },
    api_key: { label: 'API Key', color: 'default' },
    knowledge_base: { label: '知识库', color: 'default' },
    workflow: { label: '工作流', color: 'default' },
    tool: { label: '工具', color: 'default' },
  },
  breaker: { open: { label: '熔断中', color: 'error' }, half_open: { label: '熔断探测中', color: 'warning' }, closed: { label: '正常', color: 'success' } },
  nodeStatus: {
    pending: { label: '等待', color: 'default' },
    running: { label: '运行中', color: 'processing' },
    success: { label: '成功', color: 'success' },
    failed: { label: '失败', color: 'error' },
    awaiting_review: { label: '待审核', color: 'warning' },
  },
  provider: {
    openai: { label: 'OpenAI 兼容', color: 'default' },
    deepseek: { label: 'DeepSeek', color: 'default' },
    qwen: { label: '通义千问', color: 'default' },
    moonshot: { label: '月之暗面', color: 'default' },
    zhipu: { label: '智谱', color: 'default' },
  },
  visibility: { true: { label: '公开', color: 'success' }, false: { label: '受限', color: 'warning' } },
}

export const statusLabel = (domain: StatusDomain, value: string | boolean | null | undefined): string => {
  if (value === null || value === undefined) return '-'
  return STATUS[domain][String(value)]?.label ?? String(value)
}

// 筛选下拉的选项（与标签同源）
export const statusOptions = (domain: StatusDomain) => Object.entries(STATUS[domain]).map(([value, meta]) => ({ value, label: meta.label }))

export const roleLabel: Record<string, string> = Object.fromEntries(Object.entries(STATUS.role).map(([k, v]) => [k, v.label]))

// 节点类型的中文名（与工作流编辑器节点库一致）
export const NODE_TYPE_LABEL: Record<string, string> = {
  start: '开始', end: '结束', agent: '智能体', tool: '工具', condition: '条件', kb_retrieval: '知识库检索',
  code: '代码执行', http: 'HTTP 请求', loop: '循环', human_review: '人工审核', parallel: '并行', join: '汇聚',
}
