# 前端铁律卡片

完整规范见 `../docs/05-开发规范.md` 与 `../docs/07-前端规范.md`，本卡片只列改代码前必须记住的几条。

1. 改文件先读完整，再精确替换。
2. 改完必验：`npx tsc --noEmit` 与 `npm run build`；改过 `vite.config.ts`（分块 / 反代 / 环境变量）还要 `vite preview` 跑生产包；界面效果由使用者决定谁来验证，不自作主张。
3. 列表页用 `ListPage` 骨架、详情页用 `DetailPage` 骨架；页面根元素 `flex: 1; minHeight: 0`，顶部区 `flexShrink: 0`，表格包在 `fixed-table-wrapper` 里；禁止写死 `calc` / `100vh` 高度，禁止整页滚动。
4. 请求只在 `src/api/<域>.ts` 封装一次（`index.ts` 只 re-export），组件里不写 `axios / fetch`；错误提示用 `errorText(e, '操作失败')`。
5. 加载 / 空 / 错误三态互斥，不留静默 `catch {}`；列表用 `usePagedList`，详情 / 抽屉用 `useAsyncData`，筛选用 `useQueryState` 同步 URL。
6. 状态上屏只走 `StatusTag` + `constants/status.ts`，关联跳转只走 `ResourceLink`；抽屉里不再叠抽屉，要编辑用弹窗。
7. 主色 `#1e40af`、侧边栏 `#1f2937`、背景 `#f5f6f8`；禁止紫色渐变；品牌文案"智枢·智能体平台"不得改。
8. 新代码不新增 `any`；单文件超过 300 行就拆（页面编排 ≤ 150、列定义 ≤ 100、表单 / 抽屉 ≤ 150）。
9. 轮询必须有界：只在有未完成对象时轮询、页面不可见时暂停、卸载时清理；系统状态只从 `useSystemStatus()` 取。
10. 移动端用 `Grid.useBreakpoint()` 判断，侧边栏收 Drawer。
