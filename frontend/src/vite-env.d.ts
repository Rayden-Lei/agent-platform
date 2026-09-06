/// <reference types="vite/client" />

// 构建时注入的环境变量（.env / .env.local，前缀必须是 VITE_）
interface ImportMetaEnv {
  /** 登录页页脚提示，如演示环境的默认账号；不配置则不显示 */
  readonly VITE_LOGIN_HINT?: string
  /** 开发 / preview 反代的后端地址（只在 vite.config.ts 里读，不进产物） */
  readonly VITE_API_TARGET?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
