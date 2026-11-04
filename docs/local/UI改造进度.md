# UI 改造进度存档（antd → shadcn/ui）

> 更新时间：2026-11-04 20:15
> 用途：上下文压缩后的交接单。接着做时先看这里，再看 `git log --oneline -8`。

## 一、目标与已完成

把全站从 ant design 换成 **shadcn/ui + Tailwind v4**，最终删掉 antd、升 React 19。

| 项 | 状态 |
|---|---|
| antd / @ant-design/icons 源码引用 | **0**（从 121 个文件清到 0） |
| `styles.css` 里的 `.ant-*` 选择器 | **0**（只剩一句注释提到 .ant-btn） |
| antd / @ant-design/icons 依赖 | 已 npm uninstall |
| vendor 包体积 | 2.2MB → **1.3MB** |
| tsc / vite build | 通过 |
| 8 套配色 + 玻璃开关 | 已接入 shadcn 语义色，切换自动生效 |

## 二、关键文件（改之前先读）

- `src/styles/theme.css` —— 设计 token。8 套主题靠 `data-theme`，`@theme inline` 把 shadcn 语义色映射到项目 token。
  语义色（2026-11-04 新增）：`--danger/-soft`、`--success/-soft`、`--warning/-soft`、`--info/-soft`，深色主题另有提亮版本。
- `src/components/shadcn/` —— shadcn 生成的组件（**不要**放进 `components/ui/`，macOS 大小写不敏感会与既有 Button.tsx 冲突）。
- `src/components/ui/Modal.tsx` —— 弹窗封装：固定 `max-h-[calc(100dvh-3rem)]`，头脚不滚只有正文滚，支持 `dismissible`。
- `src/components/ui/Drawer.tsx` —— 抽屉封装（右侧、整高）。长表单/详情用它，短表单用 Modal。
- `src/components/ui/Button.tsx` / `Badge.tsx` —— shadcn 底的项目包装，**都已 forwardRef**（React 18 下 Radix asChild 需要）。
- `src/components/ui/confirm.tsx` —— 全局确认框（替代 antd Modal.confirm），根节点挂 `<ConfirmHost />`。
- `src/components/table/DataTable.tsx` —— 列表统一用它的 `DataColumn<T>`，支持展开行 `expand`。
- `src/pages/AgentEditor.tsx` / `pages/WorkflowEditor.tsx` —— 两个最复杂的页面，已改为受控 state。

## 三、剩余待办（按顺序）

1. **lucide 图标尺寸**：antd 图标继承 font-size，lucide 默认 24px。
   - `components/layout/SideNav.tsx` 菜单图标 span 加 `[&>svg]:size-[15px]`
   - `components/common/ResourceLink.tsx` 图标 span 加 `[&>svg]:size-3.5`
   - 顺带看 `pages/workflow/FlowNode.tsx`、`PaletteList`
2. 跑 `npx tsc --noEmit && npx vite build`，提交（styles.css + theme.css + Badge + 图标尺寸）
3. **实看三处**（都还没肉眼确认）：
   - `/agents/272?tab=channels` 的「二维码」按钮，弹层里要出真二维码
   - 该页右上操作区（对话/分享/下线/编辑/删除/返回）位置是否已上移
   - `/runs` 筛选条（智能体/工作流下拉与其它控件是否等高 32px）
4. **升 React 19**：react/react-dom + @types/react@19 + @types/react-dom@19（antd 已删，不再需要 patch 包）
5. 更新 `docs/07-前端规范.md`：还写着旧配色 `#1e40af`、`tech-card`，与现在的 token 体系不符
6. 全站走查一遍（8 套主题 × 明暗 × 移动端）

## 四、环境与坑

- 前端：`cd agent-platform/frontend && npx vite --host 0.0.0.0 --port 5173`，日志 `/tmp/fe.log`
- 后端：8000（`ENV_FILE=.env.local`），日志 `/tmp/be.log`；登录 admin / admin123456
- **装完新依赖必须 `rm -rf node_modules/.vite` 再重启 vite**，否则报 `504 (Outdated Optimize Dep)`，连带页面动态导入失败白屏（2026-11-04 踩过：qrcode.react）
- `tools.write` 偶发挂起 → 改用 `sed -i ''` 或 `tools.edit`
- Playwright 导航常 60s 超时 → 关页重开 + 重新登录
- shadcn 的 `button.tsx`/`badge.tsx` 原生成代码是 React 19 写法（ref 当普通 prop），已手工改成 forwardRef，**重新 `shadcn add` 时要注意别覆盖**
- `@ant-design/plots` 是图表库不是 antd 组件库，**保留**，只换外层卡片
