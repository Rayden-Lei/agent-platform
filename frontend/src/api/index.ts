// ===== 接口封装层入口 =====
// 页面只从 '../api' import 具名函数与类型；接口按领域拆在同目录各文件里（docs/07 第 2 节）。
// 新增接口前先在 src/api/ 目录按 URL 搜一遍，一个接口只封装一次。
export * from './core'
export * from './auth'
export * from './models'
export * from './agents'
export * from './prompts'
export * from './chat'
export * from './tools'
export * from './kb'
export * from './workflows'
export * from './runs'
export * from './admin'
export * from './system'
export * from './stats'
