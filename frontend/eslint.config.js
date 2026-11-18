import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

// 最小可用的 flat config：只保留"能拦住错误"的规则，不引入 prettier 之类的格式化规则
// （格式化规则会把全仓文件重排一遍，与本次任务无关）。
// - typescript-eslint recommended：类型无关的常见错误（未定义变量、无效正则、重复声明等）
// - react-hooks recommended：Hooks 调用规则 + 依赖数组（v6 的 recommended 就是这两条；
//   v7 起 recommended 会并入 React Compiler 的一批新规则，那批规则对存量代码报大量 error，
//   不属本次范围，故锁 6.1.1，见 package.json）
export default tseslint.config(
  {
    // 构建产物与依赖目录不参与检查
    ignores: ['dist/**', 'node_modules/**'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...reactHooks.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    rules: {
      // 本仓约定用 any 承接后端自由结构的 JSON（config、graph 等），需要类型的地方由 tsc strict 把关
      '@typescript-eslint/no-explicit-any': 'off',
      // 空接口 / 空对象类型在本仓用于占位扩展
      '@typescript-eslint/no-empty-object-type': 'off',
      // 允许以 _ 前缀声明"有意不用"的形参（与 tsconfig 的 noUnusedParameters 口径一致）
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
)
