# 前端铁律卡片

完整规范见 `../docs/05-开发规范.md` 与 `../docs/07-前端规范.md`，本卡片只列改代码前必须记住的几条。

1. 改文件先读完整，再精确替换。
2. 改完必验：`npx tsc --noEmit` 与 `npm run build`；界面效果由使用者决定谁来验证，不自作主张。
3. 页面根元素 `flex: 1; minHeight: 0`，顶部区 `flexShrink: 0`，列表页表格包在 `fixed-table-wrapper` 里；禁止写死 `calc` 高度，禁止整页滚动。
4. 请求只在 `src/api/index.ts` 封装一次，组件里不写 `axios / fetch`；错误提示 `e.response?.data?.detail`。
5. 加载 / 空 / 错误三态互斥，不留静默 `catch {}`。
6. 主色 `#1e40af`、侧边栏 `#1f2937`、背景 `#f5f6f8`；禁止紫色渐变；品牌文案"智枢·智能体平台"不得改。
7. 新代码不新增 `any`；单文件超过 300 行就拆。
8. 移动端用 `Grid.useBreakpoint()` 判断，侧边栏收 Drawer。
