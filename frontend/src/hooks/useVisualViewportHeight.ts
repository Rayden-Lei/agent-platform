import { useEffect, useState } from 'react'

// 可视视口高度（docs/15 CH-14）：iOS Safari 弹出键盘时只缩小可视视口、不缩小布局视口，钉在底部的输入框会被键盘挡住，
// 页面还会被整体顶上去。整页高度改用可视视口的高度、并把被顶走的滚动拉回 0，输入框就贴在键盘上沿。
// Android Chrome 靠 index.html 的 interactive-widget=resizes-content 缩小布局视口，这里的值与 100% 一致，不冲突。
// 不支持 visualViewport 的浏览器返回 undefined，调用方退回 100%。
export function useVisualViewportHeight(): number | undefined {
  const [height, setHeight] = useState<number | undefined>(() => window.visualViewport?.height)
  useEffect(() => {
    const vv = window.visualViewport
    if (!vv) return
    const update = () => {
      // 双指缩放时 height 是缩放后的可视高度，乘回 scale 才是没缩放时该有的高度
      setHeight(Math.round(vv.height * vv.scale))
      if (vv.scale === 1 && window.scrollY !== 0) window.scrollTo(0, 0)
    }
    update()
    vv.addEventListener('resize', update)
    vv.addEventListener('scroll', update)
    return () => {
      vv.removeEventListener('resize', update)
      vv.removeEventListener('scroll', update)
    }
  }, [])
  return height
}
