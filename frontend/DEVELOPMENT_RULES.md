# 前端开发规范与铁律（简版）

完整版见 docs/03-开发规范与铁律.txt

## 铁律
1. 改文件先 read 完整，再 edit。
2. 改完必验：npx tsc --noEmit
3. 布局用 flex + height 100% 自适应，禁止写死 calc 高度。

## 布局
- 页面 flex column，标题区 flexShrink 0，内容 flex 1 + minHeight 0。
- 列表页表格包 fixed-table-wrapper，表体内部滚动，分页固定底部。
- 全局 html/body/#root overflow-x hidden。

## 配色（用户明确要求）
- 主色 #1e40af 深蓝，侧边栏 #1f2937 深灰，背景 #f5f6f8。
- 禁止紫色系渐变（一股 AI 味道）。

## 品牌
产品名「智枢·智能体平台」，左上角 logo 文案不得改动。

## 技术栈
React 18 + TS + Vite + Ant Design 5 + React Router 6 + Zustand + axios + @xyflow/react

## 移动端
useBreakpoint 判断，侧边栏收 Drawer，表格横向滚动，栅格响应式。