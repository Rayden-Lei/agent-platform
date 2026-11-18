import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import type { Page, PageQuery } from '../api'
import { errorText } from '../utils/errors'
import { useQueryState } from './useQueryState'

export interface SortState { field?: string; order?: 'asc' | 'desc' }

export interface UsePagedListOptions {
  pageSize?: number
  /** 服务端筛选条件，变化时自动回到第 1 页重新加载 */
  filters?: Record<string, string | number | boolean | undefined>
  errorText?: string
  /** 默认排序；列上标 sortable 即可接入服务端排序（由 DataTable 触发 setSort） */
  defaultSort?: SortState
  /** 注入 rowSelection，选中跨页保留；筛选变化时清空 */
  selectable?: boolean
  /** 空态文案（三态互斥：加载中不显示空态；失败显示错误占位） */
  emptyText?: ReactNode
  /** 挂载即加载；详情页里的页签传 false 由页签激活时再 load */
  auto?: boolean
  /**
   * 页码与每页条数同步到 URL（刷新、分享链接、浏览器前进后退都停在同一页）。
   * 默认关闭，只给"一个页面只有一个列表"的顶层列表页显式打开：详情页页签、抽屉里的嵌入表格
   * 往往同时挂好几个（智能体详情有运行记录 / 会话 / 版本历史三张表），共用 page / page_size
   * 两个键会互相覆盖，还会互相触发重载。
   */
  syncUrl?: boolean
}

// URL 里的键与解析：默认值（page=1、本列表的默认每页条数）不写进 URL，与 useQueryState 的既有口径一致
type PageState = { page?: string; page_size?: string }
const PAGE_STATE_DEFAULTS: PageState = { page: undefined, page_size: undefined }

function parsePage(raw: string | undefined): number {
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : 1
}

function parsePageSize(raw: string | undefined, fallback: number): number {
  const n = Number(raw)
  return Number.isInteger(n) && n > 0 ? n : fallback
}

/**
 * 服务端分页列表的通用状态：页码、每页条数、总数、加载态、排序、错误态、行选择，直接喂给 DataTable。
 * 用请求序号丢弃过期响应：快速翻页或切换筛选时，先发后到的响应不会覆盖新数据。
 */
export function usePagedList<T = any>(
  fetcher: (params: PageQuery) => Promise<Page<T>>,
  options: UsePagedListOptions = {},
) {
  // selectable 只是各页面转给 DataTable 的透传选项，hook 内部不消费，故不在这里解构
  const { pageSize: initialPageSize = 20, filters, errorText: fallbackText = '加载失败', defaultSort, emptyText, auto = true, syncUrl = false } = options
  // 页码与每页条数放进 URL：刷新、分享链接、浏览器前进后退都停在同一页（与筛选的 useQueryState 同一口径）
  const [pageState, setPageState] = useQueryState(PAGE_STATE_DEFAULTS)
  const urlPage = syncUrl ? parsePage(pageState.page) : 1
  const urlPageSize = syncUrl ? parsePageSize(pageState.page_size, initialPageSize) : initialPageSize
  const [items, setItems] = useState<T[]>([]) // 当前页数据
  const [total, setTotal] = useState(0) // 服务端返回的总条数
  const [page, setPage] = useState(urlPage) // 当前页码
  const [pageSize, setPageSize] = useState(urlPageSize) // 每页条数
  const [loading, setLoading] = useState(false) // 请求中标记
  const [error, setError] = useState<string | null>(null) // 加载失败的文案；成功后清空
  const [sort, setSort] = useState<SortState>(defaultSort ?? {})
  const [selectedKeys, setSelectedKeys] = useState<number[]>([])
  const seq = useRef(0) // 请求序号，用于丢弃过期响应
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  // setPageState 的身份随 URL 变化，直接进 load 的依赖会让 load 每次都变、触发反复重载，所以走 ref
  const setPageStateRef = useRef(setPageState)
  setPageStateRef.current = setPageState
  // URL 里当前记着的页码，用来判断"这次响应是否需要写回 URL"：值没变就不写，
  // 否则每 3 秒的轮询（文档页）都会 replace 一次查询串，白白触发一次路由渲染
  const urlStateRef = useRef({ page: urlPage, pageSize: urlPageSize })
  urlStateRef.current = { page: urlPage, pageSize: urlPageSize }
  // load 内部要能重新发起一次请求（页码越界时回到最后一页），自引用只能走 ref
  const loadRef = useRef<(p: number, ps: number) => void>(() => {})
  const filtersKey = JSON.stringify(filters ?? {})
  const sortKey = `${sort.field ?? ''}:${sort.order ?? ''}`
  const triggerKey = `${filtersKey}|${sortKey}`
  // 上一次触发加载时的筛选 / 排序组合：只有它变了才回到第 1 页，其余情况（挂载、effect 重跑）沿用当前页
  const lastTrigger = useRef(triggerKey)

  const load = useCallback(async (p: number, ps: number) => {
    const mine = ++seq.current
    setLoading(true)
    try {
      const res = await fetcherRef.current({ page: p, page_size: ps, ...(filters ?? {}), sort: sort.field, order: sort.field ? sort.order : undefined })
      if (mine !== seq.current) return // 已有更新的请求发出，本次为过期响应，直接丢弃
      // 页码越界（分享的链接带着 ?page=9，但数据已经变少）：空页上仍显示"共 N 条"，回到最后一页
      if (res.items.length === 0 && res.total > 0 && p > 1) {
        const last = Math.max(1, Math.ceil(res.total / res.page_size))
        if (last !== p) {
          loadRef.current(last, res.page_size)
          return
        }
      }
      setItems(res.items)
      setTotal(res.total)
      setPage(res.page)
      setPageSize(res.page_size)
      if (syncUrl && (res.page !== urlStateRef.current.page || res.page_size !== urlStateRef.current.pageSize)) {
        // 默认值（page=1、本列表的默认每页条数）不写进 URL，与 useQueryState 的既有口径一致
        urlStateRef.current = { page: res.page, pageSize: res.page_size }
        setPageStateRef.current({
          page: res.page === 1 ? undefined : String(res.page),
          page_size: res.page_size === initialPageSize ? undefined : String(res.page_size),
        })
      }
      setError(null)
    } catch (e) {
      if (mine !== seq.current) return
      const text = errorText(e, fallbackText)
      setError(text)
      toast.error(text)
    } finally {
      if (mine === seq.current) setLoading(false)
    }
    // filters / sort 用序列化后的字符串参与依赖，避免调用方每次渲染传新对象导致无限重载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, sortKey, fallbackText])

  useEffect(() => {
    if (!auto) return
    setSelectedKeys([]) // 筛选或排序变化：选中项不再有意义
    const changed = lastTrigger.current !== triggerKey
    lastTrigger.current = triggerKey
    // 筛选或排序变化：回到第 1 页；否则沿用当前页（首次挂载时它就是 URL 里带来的那一页）。
    // 不同步 URL 的嵌入表格沿用当前每页条数（服务端可能已把它夹到上限）
    load(changed ? 1 : page, changed || !syncUrl ? pageSize : urlPageSize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, auto])

  // URL 被外部改动（浏览器前进后退、别人给的链接）时按 URL 重新取数。
  // 自己翻页写回 URL 的那次变化不会触发这里：load 成功时已经同步把 page / pageSize 设成了同一对值。
  useEffect(() => {
    if (!syncUrl) return
    if (urlPage === page && urlPageSize === pageSize) return
    // 先记下 URL 的目标值，load 回来时就不会再把它写一遍（同样的查询串不必再 replace 一次）
    urlStateRef.current = { page: urlPage, pageSize: urlPageSize }
    load(urlPage, urlPageSize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlPage, urlPageSize, syncUrl])

  loadRef.current = (p, ps) => { void load(p, ps) }

  // 手动刷新：沿用当前页码与每页条数重新请求
  const reload = useCallback(() => load(page, pageSize), [load, page, pageSize])
  const clearSelection = useCallback(() => setSelectedKeys([]), [])

  // items 当前页数据 / total 总条数 / load 指定页码加载 / reload 原地刷新 / error 失败文案
  // emptyText 必须一起返回：传了却没返回，调用方写了带操作按钮的空态也永远不显示
  // （2026-11-08 前它是死参数，向量模型页因此只剩裸的"暂无数据"，新用户找不到创建入口）。
  return { items, total, page, pageSize, loading, error, sort, setSort, selectedKeys, setSelectedKeys, clearSelection, load, reload, emptyText }
}