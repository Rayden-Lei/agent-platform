import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { message } from 'antd'
import type { TableProps } from 'antd'
import type { Page, PageQuery } from '../api'
import { errorText } from '../utils/errors'

export interface SortState { field?: string; order?: 'asc' | 'desc' }

export interface UsePagedListOptions {
  pageSize?: number
  /** 服务端筛选条件，变化时自动回到第 1 页重新加载 */
  filters?: Record<string, string | number | boolean | undefined>
  errorText?: string
  /** 默认排序；列上用 sortProps(field) 接入表头排序 */
  defaultSort?: SortState
  /** 注入 rowSelection，选中跨页保留；筛选变化时清空 */
  selectable?: boolean
  /** 空态文案（三态互斥：加载中不显示空态；失败显示错误占位） */
  emptyText?: ReactNode
  /** 挂载即加载；详情页里的页签传 false 由页签激活时再 load */
  auto?: boolean
}

/**
 * 服务端分页列表的通用状态：页码、每页条数、总数、加载态、排序、错误态、行选择，以及可直接展开到 <Table> 的 tableProps。
 * 用请求序号丢弃过期响应：快速翻页或切换筛选时，先发后到的响应不会覆盖新数据。
 */
export function usePagedList<T = any>(
  fetcher: (params: PageQuery) => Promise<Page<T>>,
  options: UsePagedListOptions = {},
) {
  const { pageSize: initialPageSize = 20, filters, errorText: fallbackText = '加载失败', defaultSort, selectable = false, emptyText, auto = true } = options
  const [items, setItems] = useState<T[]>([]) // 当前页数据
  const [total, setTotal] = useState(0) // 服务端返回的总条数
  const [page, setPage] = useState(1) // 当前页码
  const [pageSize, setPageSize] = useState(initialPageSize) // 每页条数
  const [loading, setLoading] = useState(false) // 请求中标记
  const [error, setError] = useState<string | null>(null) // 加载失败的文案；成功后清空
  const [sort, setSort] = useState<SortState>(defaultSort ?? {})
  const [selectedKeys, setSelectedKeys] = useState<number[]>([])
  const seq = useRef(0) // 请求序号，用于丢弃过期响应
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const filtersKey = JSON.stringify(filters ?? {})
  const sortKey = `${sort.field ?? ''}:${sort.order ?? ''}`

  const load = useCallback(async (p: number, ps: number) => {
    const mine = ++seq.current
    setLoading(true)
    try {
      const res = await fetcherRef.current({ page: p, page_size: ps, ...(filters ?? {}), sort: sort.field, order: sort.field ? sort.order : undefined })
      if (mine !== seq.current) return // 已有更新的请求发出，本次为过期响应，直接丢弃
      setItems(res.items)
      setTotal(res.total)
      setPage(res.page)
      setPageSize(res.page_size)
      setError(null)
    } catch (e) {
      if (mine !== seq.current) return
      const text = errorText(e, fallbackText)
      setError(text)
      message.error(text)
    } finally {
      if (mine === seq.current) setLoading(false)
    }
    // filters / sort 用序列化后的字符串参与依赖，避免调用方每次渲染传新对象导致无限重载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, sortKey, fallbackText])

  useEffect(() => {
    if (!auto) return
    setSelectedKeys([]) // 筛选或排序变化：选中项不再有意义
    load(1, pageSize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, auto]) // 首次与筛选 / 排序变化：回到第 1 页

  // 手动刷新：沿用当前页码与每页条数重新请求
  const reload = useCallback(() => load(page, pageSize), [load, page, pageSize])
  const clearSelection = useCallback(() => setSelectedKeys([]), [])

  // 列定义上展开：{ ...sortProps('latency_ms') } 即可让表头可排序（服务端排序）
  const sortProps = useCallback((field: string) => ({
    sorter: true as const,
    sortOrder: sort.field === field ? (sort.order === 'asc' ? ('ascend' as const) : ('descend' as const)) : null,
  }), [sort])

  // 可直接展开到 antd <Table> 的属性：数据源、加载态、分页配置（翻页即触发 load）、排序回调、行选择、空态
  const tableProps = useMemo(() => {
    const onChange: TableProps<T>['onChange'] = (_pagination, _filters, sorter) => {
      const s = Array.isArray(sorter) ? sorter[0] : sorter
      const field = s?.order ? String(s.columnKey ?? s.field ?? '') : undefined
      setSort(field ? { field, order: s?.order === 'ascend' ? 'asc' : 'desc' } : {})
    }
    return {
      dataSource: items,
      loading,
      onChange,
      pagination: {
        current: page,
        pageSize,
        total,
        showSizeChanger: true,
        showTotal: (t: number) => '共 ' + t + ' 条',
        position: ['bottomRight'] as ['bottomRight'],
        onChange: (p: number, ps: number) => load(p, ps),
      },
      ...(selectable ? {
        rowSelection: {
          selectedRowKeys: selectedKeys,
          onChange: (keys: React.Key[]) => setSelectedKeys(keys.map(Number)),
          preserveSelectedRowKeys: true,
        },
      } : {}),
      ...(emptyText !== undefined ? { locale: { emptyText: loading ? ' ' : error ? `加载失败：${error}` : emptyText } } : {}),
    }
  }, [items, loading, page, pageSize, total, load, selectable, selectedKeys, emptyText, error])

  // items 当前页数据 / total 总条数 / load 指定页码加载 / reload 原地刷新 / error 失败文案
  return { items, total, page, pageSize, loading, error, sort, setSort, sortProps, selectedKeys, setSelectedKeys, clearSelection, load, reload, tableProps }
}
