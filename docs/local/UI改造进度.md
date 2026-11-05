# UI 改造进度存档（antd → shadcn/ui）

> 更新时间：2026-11-05 10:50 ｜ 状态：**已完成**（改造 + 文档同步 + 全站走查 + 破坏性确认标红均已收口）
> 用途：上下文压缩后的交接单。接着做时先看这里，再看 `git log --oneline -8`。

## 一、目标与已完成

把全站从 ant design 换成 **shadcn/ui + Tailwind v4**，最终删掉 antd、升 React 19。

| 项 | 状态 |
|---|---|
| antd / @ant-design/icons 源码引用 | **0**（从 121 个文件清到 0） |
| `styles.css` 里的 `.ant-*` 选择器 | **0** |
| antd / @ant-design/icons 依赖 | 已 npm uninstall（`@ant-design/v5-patch-for-react-19` 从未安装，无需处理） |
| vendor 包体积 | 2.2MB → **1.4MB**（引入 liquid-glass-react 后回升） |
| React | **19.3.1**（`@types/react` 19.3.0） |
| 8 套配色 + 玻璃开关 | 已接入 shadcn 语义色，切换自动生效；配色对比度全部达标 |
| 液态玻璃 | 已换成 `liquid-glass-react@1.1.1`（手写版已删） |
| 破坏性确认 | 21 处统一标红（`danger`） |
| 全站走查 | 256 组（8 主题 × 玻璃开关 × 桌面/移动）全过 |
| tsc / vite build | 通过 |

## 二、关键文件（改之前先读）

- `src/styles/theme.css` —— 设计 token。8 套主题靠 `data-theme`，`@theme inline` 把 shadcn 语义色映射到项目 token。
  语义色：`--danger/-soft`、`--success/-soft`、`--warning/-soft`、`--info/-soft`，深色主题另有提亮版本。
- `src/components/shadcn/` —— shadcn 生成的组件（**不要**放进 `components/ui/`，macOS 大小写不敏感会与既有 Button.tsx 冲突）。
- `src/components/ui/Modal.tsx` —— 弹窗封装：固定 `max-h-[calc(100dvh-3rem)]`，头脚不滚只有正文滚，支持 `dismissible`。
- `src/components/ui/Drawer.tsx` —— 抽屉封装（右侧、整高）。长表单/详情用它，短表单用 Modal。
- `src/components/ui/Button.tsx` / `Badge.tsx` —— shadcn 底的项目包装（已 forwardRef，React 19 下也不需要去掉）。
- `src/components/ui/confirm.tsx` —— 全局确认框（替代 antd Modal.confirm），根节点挂 `<ConfirmHost />`。
- `src/components/ui/InlineConfirm.tsx` —— 行内二次确认。**内部改成走全局 confirm() 弹窗**，调用点不用动（18 个文件 30+ 处）。
  文案按第一个「？」拆成标题 + 说明；新增 `danger` 属性把确认按钮变红。
- `src/components/theme/GlassSurface.tsx` —— 液态玻璃底衬，见下节。
- `src/components/table/DataTable.tsx` —— 列表统一用它的 `DataColumn<T>`，支持展开行 `expand`。
- `src/pages/AgentEditor.tsx` / `pages/WorkflowEditor.tsx` —— 两个最复杂的页面，已改为受控 state。

## 三、液态玻璃（liquid-glass-react）—— 五个坑

用法：`<GlassSurface enabled={glass} />` 只画玻璃、**不接管内容**；内容留在调用方正常文档流里（父级要 `relative`）。
关闭时组件 `return null`，所以开关两种状态布局完全一致（曾因把内容塞进绝对定位层，导致关掉玻璃后按钮位置偏移）。

库的这几处内联样式/默认行为都会打架，全部在 `theme.css` 的 `.lg-surface` 里覆盖：

| 坑 | 现象 | 覆盖方式 |
|---|---|---|
| `translate(-50%,-50%)` 居中 | 整层偏出容器半个身位，糊成一片马赛克 | `top/left` 必须给 `'50%'`，**不能写 `0px`** |
| `display: inline-flex`（内联样式） | 内容层收缩成内容宽（顶栏 1228 宽时只有 341） | `display: flex !important` |
| 内容层高度不撑满 | 侧栏导航只占上半截、垂直居中 | `.glass > div:last-child { width/height: 100% }` |
| `overflow: hidden`（内联） | 顶栏里向下展开的浮层被裁掉，弹窗"打不开" | `overflow: visible !important` |
| `box-shadow: 0 12px 40px`（内联） | 铺满侧栏时一大团黑边 | `box-shadow: none !important` |

**还有一处不是覆盖能解决的**：库用 `feDisplacementMap` 做折射，位移量默认 70px。
顶栏只有 55px 高，位移远大于元素本身，Chromium 把整条渲染成 **RGB≈156 的灰带**（页面背景 253）。
已在 `.glass__warp` 上 `filter: none !important` 关掉位移滤镜，只保留 `backdrop-filter` 的模糊 + 饱和 + 46% 淡色。
代价是没有折射扭曲，只剩磨砂质感；这个尺寸下折射本来也看不出来。

**底色位置很关键**：淡色要加在 `glass__warp`（模糊层）自己身上，不能加在 `.glass` 上——
元素自身的 background 画在 backdrop-filter **之后**；加在 `.glass` 上会被模糊层一起采样，等于糊白板。

## 四、文档同步（2026-11-05 已完成）

- `docs/07-前端规范.md` 升到 V3.0：技术栈、组件分层（新增 2.1 节）、`DataTable` 用法、设计令牌、表单/断点/输入法、自查清单全部按现状重写；过时的 `#1e40af`、`.tech-card`、`sortProps`、`tableProps`、`destroyOnHidden`、`confirmLoading`、`Grid.useBreakpoint` 已清除。
- `docs/05-开发规范.md` 第 10 条技术栈：React 18 / Ant Design 5 → React 19 / Tailwind v4 / shadcn/ui。
- `docs/02-架构设计.md`：`main.tsx` 职责与 `store/` 清单。
- `docs/09-演进路线.md`、`docs/14-页面深度优化方案.md`：vendor 块体积、antd 遗留项结清。

## 五、全站走查（2026-11-05，已完成）

用 Playwright 脚本跑 8 主题 × 玻璃开/关 × 桌面 14 页 + 移动 4 页，共 **256 组，0 问题、0 控制台错误**。
脚本留在 `/tmp/audit2.mjs`（临时文件，需要时照它的判定口径重写）。判定项与当轮修的东西：

| 判定 | 口径 | 当轮发现并修掉 |
|---|---|---|
| 文字对比度 | WCAG AA：正文 4.5、大字 3 | `--fg-subtle` 各主题 4.2~4.4 → 4.65+；暖砂/品红主色加深；`--danger` 4.43 → 4.73 |
| 主色底上的前景 | 深色主题主色偏亮 | 工作台横幅、登录卡片头、品牌 logo 从写死 `#fff` 改 `--accent-fg`（深空 2.8 → 6.9） |
| 命中区 | WCAG 2.5.8：目标 ≥24×24 | 选择框 16→32、展开箭头 20→32、启停开关 18→44 高、提示条关闭 22→38、表格名称按钮 20→32，均用 `::after` 扩，视觉不变 |
| 整页滚动 | 文档本身不许滚 | 全部达标（一直没坏） |
| 横向溢出 | 不许出横向滚动条 | 全部达标 |
| 控制台 | 不许有 error | favicon 404（已补 `public/favicon.svg`） |

配色改动值（备查）：暖砂主色 `#B45309 → #AA4E09`、品红 `#C026D3 → #AE24C1`、危险色 `#DC2626 → #D42424`；
主题色卡（`store/theme.ts` 的 `THEMES`）要跟 `theme.css` 同一个值，改一个记得改另一个。

## 六、剩余待办

无。后续新增主题时，把新配色按上表的对比度口径算一遍再合入。

## 七、环境与坑

- 前端：`cd agent-platform/frontend && npx vite --host 0.0.0.0 --port 5173`，日志 `/tmp/fe.log`
- 后端：8000（`ENV_FILE=.env.local`），日志 `/tmp/be.log`；登录 admin / `Agent-2026-Kx7m`（2026-11-04 已改，旧的 admin123456 失效）
- **装完新依赖必须 `rm -rf node_modules/.vite` 再重启 vite**，否则报 `504 (Outdated Optimize Dep)` 连带白屏
- `tools.write` 偶发挂起 → 改用 `sed -i ''` 或 `tools.edit`
- Playwright 导航常 60s 超时 → 关页重开 + 重新登录；元素寻址用 `target` 不是 `ref`
- **截图先直接看**：`read_image` 能读 PNG，肉眼判断颜色和布局最快。要精确数值（比如"顶栏是不是被渲染成灰带"）再用像素分析：
  `browser_run_code_unsafe` 传**代码字符串**截图，再用 Node `zlib` 解 PNG 反滤波，按区域算 RGB/方差。
  这次就是靠它定位灰带的（顶栏 156 vs 内容区 253）。`browser_run_code_unsafe` 传函数会报 `__fn__ is not a function`。
- shadcn 的 `button.tsx`/`badge.tsx` 原生成代码是 React 19 写法（ref 当普通 prop），已手工改成 forwardRef，**重新 `shadcn add` 时要注意别覆盖**
- `@ant-design/plots` 是图表库不是 antd 组件库，**保留**，只换外层卡片
- 外网访问：`cloudflared tunnel --url http://localhost:5173`，Vite 需带 `VITE_ALLOWED_HOSTS=<隧道域名>,.trycloudflare.com`，preview 模式还要 `preview.allowedHosts`
