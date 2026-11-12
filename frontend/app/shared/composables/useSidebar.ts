/**
 * App shell sidebar state. `collapsed` hides the desktop sidebar and is remembered in a cookie; `mobileOpen` is the
 * sheet on narrow screens and is never persisted.
 */
export const useSidebar = () => {
  const collapsed = useCookie<boolean>('sidebar-collapsed', {
    default: () => false,
    maxAge: 60 * 60 * 24 * 365,
    sameSite: 'lax',
  })
  const mobileOpen = useState('sidebar-mobile-open', () => false)
  return { collapsed, mobileOpen }
}
