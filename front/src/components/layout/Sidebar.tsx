import { NavLink, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  FileText,
  MessageSquare,
  History,
  Activity,
  GraduationCap,
  Library,
  Network,
  Settings,
  User,
  Info,
  LogOut,
  Columns2,
} from 'lucide-react'
import BrandMark from '../common/BrandMark'
import { useUserStore } from '../../stores/useUserStore'
import { authApi } from '../../api/auth'

const navItems = [
  { path: '/notes', icon: FileText, labelKey: 'nav.notes' },
  { path: '/chat', icon: MessageSquare, labelKey: 'nav.chat' },
  { path: '/sessions', icon: History, labelKey: 'nav.sessions' },
  { path: '/usage', icon: Activity, labelKey: 'nav.usage' },
  { path: '/review', icon: GraduationCap, labelKey: 'nav.review' },
  { path: '/knowledge', icon: Library, labelKey: 'nav.knowledge' },
  { path: '/graph', icon: Network, labelKey: 'nav.graph' },
]

const bottomItems = [
  { path: '/profile', icon: User, labelKey: 'nav.profile' },
  { path: '/settings', icon: Settings, labelKey: 'nav.settings' },
  { path: '/about', icon: Info, labelKey: 'nav.about' },
]

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const logout = useUserStore((s) => s.logout)

  const handleLogout = async () => {
    try { await authApi.logout() } catch { /* ignore */ }
    logout()
    navigate('/login')
  }

  return (
    <aside
      className={`flex flex-col border-r border-[var(--color-border)] bg-[var(--color-card)] shrink-0 transition-all duration-300 ${
        collapsed ? 'w-16' : 'w-60'
      }`}
    >
      <div className="flex items-center justify-between px-5 h-16 border-b border-[var(--color-border)]">
        {!collapsed && (
          <div className="flex min-w-0 items-center gap-2.5">
            <BrandMark size={20} className="shrink-0 text-[var(--color-text)]" />
            <h1 className="font-heading text-lg font-semibold text-[var(--color-text)] truncate">
              {t('app.name')}
            </h1>
          </div>
        )}
        <button
          onClick={onToggle}
          className="p-1.5 rounded-md text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text)] transition-colors"
          title={collapsed ? t('nav.expand') : t('nav.collapse')}
        >
          <Columns2 size={18} className={`transition-transform duration-300 ${collapsed ? 'rotate-180' : ''}`} />
        </button>
      </div>

      <nav className="flex-1 px-3 space-y-1">
        {navItems.map(({ path, icon: Icon, labelKey }) => (
          <NavLink
            key={path}
            to={path}
            end={path === '/notes'}
            className={({ isActive }) =>
              `relative flex items-center gap-3 px-3 py-2 rounded-[3px] text-sm ${
                isActive
                  ? 'text-[var(--color-text)] font-medium before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[2px] before:-translate-y-1/2 before:bg-[var(--color-text)]'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text)]'
              } ${collapsed ? 'justify-center' : ''}`
            }
            title={collapsed ? t(labelKey) : undefined}
          >
            <Icon size={18} />
            {!collapsed && t(labelKey)}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[var(--color-border)] space-y-1">
        {bottomItems.map(({ path, icon: Icon, labelKey }) => (
          <NavLink
            key={path}
            to={path}
            className={({ isActive }) =>
              `relative flex items-center gap-3 px-3 py-2 rounded-[3px] text-sm ${
                isActive
                  ? 'text-[var(--color-text)] font-medium before:absolute before:left-0 before:top-1/2 before:h-4 before:w-[2px] before:-translate-y-1/2 before:bg-[var(--color-text)]'
                  : 'text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-text)]'
              } ${collapsed ? 'justify-center' : ''}`
            }
            title={collapsed ? t(labelKey) : undefined}
          >
            <Icon size={18} />
            {!collapsed && t(labelKey)}
          </NavLink>
        ))}
        <button
          onClick={handleLogout}
          className={`flex items-center gap-3 px-3 py-2.5 rounded-md text-sm w-full text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-secondary)] hover:text-[var(--color-danger)] transition-colors ${
            collapsed ? 'justify-center' : ''
          }`}
          title={collapsed ? t('nav.logout') : undefined}
        >
          <LogOut size={18} />
          {!collapsed && t('nav.logout')}
        </button>
      </div>
    </aside>
  )
}
