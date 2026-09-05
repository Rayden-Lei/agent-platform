import { lazy } from 'react'

// @ant-design/plots 按需懒加载：任何没挂图表的页面都不会下载 G2（vite 把它单独分成 charts 块）。
export const LazyLine = lazy(() => import('@ant-design/plots').then((m) => ({ default: m.Line })))
export const LazyColumn = lazy(() => import('@ant-design/plots').then((m) => ({ default: m.Column })))
export const LazyPie = lazy(() => import('@ant-design/plots').then((m) => ({ default: m.Pie })))
export const LazyTinyLine = lazy(() => import('@ant-design/plots').then((m) => ({ default: m.Tiny.Line })))
