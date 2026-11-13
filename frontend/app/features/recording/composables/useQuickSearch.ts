/** Open state of the ⌘K dialog, shared by the sidebar «Поиск» item and the keyboard shortcut. */
export const useQuickSearch = () => {
  const open = useState('recording-quick-search', () => false)
  return {
    open,
    show: () => {
      open.value = true
    },
  }
}
