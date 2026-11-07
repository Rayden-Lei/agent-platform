# 前端交互摩擦点扫描（task-11）

扫描时间：2026-11-08 · 只读，未改任何代码、未起服务
口径：`docs/07-前端规范.md`（第 1 节滚动、第 4 节三态、第 8 节表单、第 9 节拆分、第 6 节禁写死色值）
覆盖：`pages/Skills.tsx`、`pages/McpServers.tsx`、`components/skills/*`、`components/mcp/*`、`pages/Tools.tsx`、`components/tools/ToolDrawer.tsx`、`components/layout/ListPage.tsx`、`hooks/usePagedList.ts`、`components/layout/FilterBar.tsx`、`components/layout/DetailPage.tsx`、`components/ui/Drawer.tsx`、`pages/Schedules.tsx`、`pages/Chat.tsx`、`components/chat/ConversationList.tsx`、`pages/EmbeddingModels.tsx`、`pages/Dashboard.tsx`、`pages/SystemSettings.tsx`
（261 个 ts/tsx 里逐页通读了 27 个页面 + 上述组件；未逐行读 `components/shadcn/`、图表、工作流画布内部）

按「新用户会不会卡住」排序。

---

## 1. `usePagedList` 的 `emptyText` 是死参数，已导致一个页面空态无引导

- **位置**：`frontend/src/hooks/usePagedList.ts:31`（解构了 `emptyText`）、`:79`（返回值里没有它）
- **现象**：`emptyText` 从 options 里解构出来后再没出现过，也从不返回给调用方。`DataTable` 只认自己的 `empty` prop。规范第 7 节写的"表格用 `usePagedList` 的 `emptyText` 选项"与实现不符。
- **真实后果**：`pages/EmbeddingModels.tsx:46` 认真写了空态文案 + "新增向量模型"按钮，但 `:127-143` 的 `<DataTable>` 没传 `empty` → 向量模型为空时用户看到的是裸的「暂无数据」，**找不到新增入口**。这是新用户配知识库的第一步，直接卡死。
- **修法**：二选一。(a) hook 把 `emptyText` 返回出去，页面透传给 `DataTable`；(b) 删掉这个参数，规范改成"空态只走 `DataTable empty`"，并修 `EmbeddingModels`。倾向 (a)，已有 8 个页面在用。
- 同类页面已自查：Skills / McpServers / Tools / Models / PromptTemplates / Users / Agents 都同时传了 `empty`，不受影响。

## 2. 删除会话：无二次确认 + 失败完全静默

- **位置**：`frontend/src/components/chat/ConversationList.tsx:73`、`frontend/src/pages/Chat.tsx:252-256`
- **现象**：列表项 hover 出现垃圾桶，点一下就删，没有 `InlineConfirm`（全站其他删除都有）。更严重的是 `removeConversation` 里 `await deleteConversation(id)` **没有 try/catch** —— 请求失败时是一个未捕获的 rejected promise，**没有任何 toast**，用户以为删掉了，刷新才回来。
- **修法**：外面包 `InlineConfirm`（文案"删除会话？消息记录一并删除"），函数体加 `try/catch + toast.error(errorText(e, '删除失败'))`。

## 3. 表单错误提示在抽屉最底部，用户点保存后看不到

- **位置**：`components/skills/SkillForm.tsx:224`、`components/mcp/McpServerForm.tsx:298`
- **现象**：`{error && <p ...>}` 是表单的最后一个元素。抽屉正文区是可滚动区（`ui/Drawer.tsx:38`），800px 宽、内容一屏放不下时，**点「保存」→ 后端 409 重名 → 错误文案渲染在屏幕外**，用户看到的是"按钮闪了一下没反应"。
- **修法**：错误条钉在 footer 上方（和按钮同一行或紧贴其上），或在 `setError` 后 `scrollIntoView`；同时把字段级错误挂到对应 `Input` 下方，而不是所有错误挤在末尾。

## 4. 字段校验没有定位到字段

- **位置**：`components/skills/SkillForm.tsx:75-85`（`validate` 返回单个字符串）、`components/mcp/McpServerForm.tsx:101-118`（`buildPayload` 同理）
- **现象**：`validate` 返回第一个不通过的文案，塞进统一的 `error`。`name` 有 `aria-invalid`（:145）但只在输入时就红，提交时的报错不会让对应字段变红/聚焦。用户填了 5 个字段，只告诉他"请填写描述"，还得自己找。
- **修法**：`validate` 返回 `Record<field, string>`，每个字段下渲染自己的错误，提交时聚焦第一个错误字段。规范第 8 节要求用 `react-hook-form`，这两处是手写受控组件，可以直接吃 RHF 的 `formState.errors`。

## 5. 统计 / 下拉的加载失败被静默吞掉

- **位置**：`pages/Skills.tsx:47`（`stats` 只用了 `stats.data`，`:103`；`stats.error` 全文件未渲染）、`pages/Schedules.tsx:105`（`workflows.data?.items ?? []`，`workflows.error` 未消费）、`pages/McpServers.tsx:51`（`catch(() => setCurrent(null))` 空吞）
- **现象**：技能统计接口挂了，页头就是不显示"共 N 个"，用户以为这页没统计；定时任务的工作流下拉加载失败时只有"全部工作流"一项，用户以为库里没工作流。规范第 4 节明令"请求失败必须有可见反馈，禁止静默"。
- **修法**：统计失败在页头 tags 位置显示"统计加载失败"+重试；下拉失败在 SelectContent 里放一行红字；`McpServers:51` 的 catch 至少 `toast.error`。

## 6. MCP 表单的保存与测试可以并发提交

- **位置**：`components/mcp/McpServerForm.tsx:165-166`
- **现象**：`testing` 时「保存」仍可点，`submitting` 时「测试连接」仍可点。对比 `SkillForm.tsx:124` 用的是 `disabled={submitting || overLimit}`。
- **修法**：两个按钮都改成 `disabled={submitting || testing}`。

## 7. `text-[var(--success)]` 大概率不生效（存疑，需浏览器确认）

- **位置**：`components/mcp/McpServerForm.tsx:281`
- **现象**：Tailwind v4 对 `text-[var(...)]` 的 font-size / color 歧义处理不确定，全仓仅此一处、无先例。若被判成 `font-size: var(--success)`，这句"连接成功"就是普通黑字，绿色提示失效。
- **修法**：改 `text-[color:var(--success)]` 或直接 `style={{ color: 'var(--success)' }}`。**我没有浏览器验证，这条请以实际渲染为准。**

## 8. 硬编码色值，深色主题下对比度不够

- **位置**：`components/chat/ConversationList.tsx:77`（`#DC2626`）、`components/chat/ChatInput.tsx:101`、`components/layout/DegradedBanner.tsx:60,66`（`#B45309`）、`pages/Schedules.tsx:80`（`#B45309`）、`components/layout/StatCards.tsx:66`（`#16a34a`）、`pages/workflow/palette.tsx:18-29`（12 个节点色）
- **现象**：规范第 6 节"页面里不许写死色值"。`#15803D` / `#B45309` 是浅色主题色，切到 `midnight` / `deep` 深色主题时这些文字几乎看不见。
- **修法**：换 `var(--success)` / `var(--warning)` / `var(--danger)`。工作流节点色可保留（那是图形语义色），但要在 theme.css 里给出深色变体。

## 9. 窄屏筛选折叠后，已生效的筛选条件不可见

- **位置**：`pages/Schedules.tsx:88`、`components/kb/DocTable.tsx:188` —— 两处 `<FilterBar>` 没传 `activeCount`
- **现象**：`FilterBar` 窄屏默认折叠，`activeCount > 0` 才自动展开并显示条数徽章（`FilterBar.tsx:22-25`）。这两处没传，用户设了筛选、折叠起来后**看不到任何"正在筛选"的提示**，会以为筛选丢了或列表数据不对。
- **修法**：补 `activeCount={Object.values(filters).filter(Boolean).length}`（其余 12 处已这么写）。

## 10. 规范第 9 节的拆分红线普遍超标（不紧急，但影响后续改动成本）

- 页面 ≤150 行：`WorkflowEditor 404`、`Chat 318`、`AgentEditor 300`、`SystemSettings 214`、`Login 201`、`AgentCreate 172`、`Skills 165`、`Schedules 155`、`EmbeddingModels 154`、`McpServers 152`
- 表单 / 抽屉 ≤150 行：`ToolForm 352`、`McpServerForm 302`、`SkillForm 261`、`ApiKeyForm 254`、`ShareSettingsForm 236`、`KbForm 206`、`ModelForm 203`、`EmbeddingModelForm 202`
- `DataTable 438` 是基础设施，可单独讨论豁免。

---

## 已核对、**没有**问题的部分（避免重复劳动）

- **滚动链**：`ListPage.tsx:16` 与 `styles.css` 的 `.fixed-table-wrapper { flex:1; min-height:0; display:flex; flex-direction:column }` 正确；`DetailPage.tsx:39/77` 的 `min-h-0 flex-1 overflow-auto` 正确；`SystemSettings.tsx:208-211`、`Chat.tsx:308-318` 都符合规范第 1 节。全仓无 `100vh`、无页面根 `overflow:auto`（Dashboard 是规范允许的唯一例外）。
- **请求分层**：`pages/` 与 `components/` 里 0 处直接 `fetch` / `axios`，全部走 `../api`。规范第 3 节达标。
- **删除二次确认**：除第 2 条外，所有删除都走了 `InlineConfirm`，文案也说清了删什么（如"删除服务器？它同步出的工具会保留但全部停用"）。
- **提交态**：19 个表单的保存按钮都做了 `disabled + "保存中…"`，只有第 6 条那处例外。
- **空 `catch {}`**：全仓 0 处。`console.log` 0 处，`window.alert/confirm` 0 处，antd 残留 0 处。
- **竞态**：列表用 `usePagedList` 的请求序号，详情用 `useAsyncData`，符合规范第 3 节。

---

## 建议的修复顺序

1. 第 1 条（空态无引导，新用户直接卡住）+ 第 2 条（误删 + 静默失败）
2. 第 3、4 条（表单错误看不到 / 不定位，改一个就能覆盖 Skills + MCP 两处）
3. 第 5、6、9 条（都是小改，半小时内能清完）
4. 第 7、8 条（视觉，需在深色主题下用浏览器确认）
5. 第 10 条（技术债，随下次改动顺手拆）
