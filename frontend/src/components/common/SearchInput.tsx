import { useEffect, useState } from 'react'
import { Input } from 'antd'
import { SearchOutlined } from '@ant-design/icons'

// 服务端搜索框：300ms 防抖后才把 q 交给筛选条件，避免每敲一个字发一次请求。
interface Props {
  value?: string
  onChange: (value?: string) => void
  placeholder?: string
  width?: number
}

export default function SearchInput({ value, onChange, placeholder = '搜索名称', width = 220 }: Props) {
  const [text, setText] = useState(value ?? '')
  useEffect(() => { setText(value ?? '') }, [value])
  useEffect(() => {
    const handle = setTimeout(() => { if ((text || undefined) !== (value || undefined)) onChange(text || undefined) }, 300)
    return () => clearTimeout(handle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])
  return <Input allowClear prefix={<SearchOutlined style={{ color: '#9ca3af' }} />} placeholder={placeholder} value={text} onChange={(e) => setText(e.target.value)} style={{ width }} />
}
