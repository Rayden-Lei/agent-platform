import { useCallback, useEffect, useRef, useState } from 'react'
import { message } from 'antd'
import type { Page, PageQuery } from '../api'

export interface UsePagedListOptions {
  pageSize?: number
  /** 服务端筛选条件，变化时自动回到第 1 页重新加载 */
  filters?: Record<string, string | number | boolean | undefined>
  errorText?: string
}

/**
 * 服务端分页列表的通用状态：页码、每页条数、总数、加载态，以及可直接展开到 <Table> 的 tableProps。
 * 用请求序号丢弃过期响应：快速翻页或切换筛选时，先发后到的响应不会覆盖新数据。
 */
export function usePagedList<T = any>(
  fetcher: (params: PageQuery) => Promise<Page<T>>,
  options: UsePagedListOptions = {},
) {
  const { pageSize: initialPageSize = 20, filters, errorText = '加载失败' } = options
  const [items, setItems] = useState<T[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(initialPageSize)
  const [loading, setLoading] = useState(false)
  const seq = useRef(0)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher
  const filtersKey = JSON.stringify(filters ?? {})

  const load = useCallback(async (p: number, ps: number) => {
    const mine = ++seq.current
    setLoading(true)
    try {
      const res = await fetcherRef.current({ page: p, page_size: ps, ...(filters ?? {}) })
      if (mine !== seq.current) return
      setItems(res.items)
      setTotal(res.total)
      setPage(res.page)
      setPageSize(res.page_size)
    } catch (e: any) {
      if (mine !== seq.current) return
      message.error(e.response?.data?.detail || errorText)
    } finally {
      if (mine === seq.current) setLoading(false)
    }
    // filters 用序列化后的字符串参与依赖，避免调用方每次渲染传新对象导致无限重载
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtersKey, errorText])

  useEffect(() => { load(1, pageSize) }, [load]) // 首次与筛选变化：回到第 1 页

  const reload = useCallback(() => load(page, pageSize), [load, page, pageSize])

  const tableProps = {
    dataSource: items,
    loading,
    pagination: {
      current: page,
      pageSize,
      total,
      showSizeChanger: true,
      showTotal: (t: number) => '共 ' + t + ' 条',
      position: ['bottomRight'] as ['bottomRight'],
      onChange: (p: number, ps: number) => load(p, ps),
    },
  }

  return { items, total, page, pageSize, loading, load, reload, tableProps }
}
