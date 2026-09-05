import { create } from 'zustand'

// 未保存改动标记：编辑器置 dirty，布局的菜单点击与 beforeunload 据此拦截，避免改完直接离开丢失内容。
// BrowserRouter + <Routes> 下没有 useBlocker，用 store + 菜单拦截替代。
interface UnsavedState {
  dirty: boolean
  setDirty: (dirty: boolean) => void
}

export const useUnsaved = create<UnsavedState>((set) => ({
  dirty: false,
  setDirty: (dirty) => set({ dirty }),
}))
