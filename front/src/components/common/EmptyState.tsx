import { FileText } from 'lucide-react'
import { useTranslation } from 'react-i18next'

interface EmptyStateProps {
  icon?: React.ReactNode
  /** 黑白线稿插图（public 下的 svg 路径）。优先于 icon。 */
  illustration?: string
  message?: string
  action?: React.ReactNode
}

export default function EmptyState({ icon, illustration, message, action }: EmptyStateProps) {
  const { t } = useTranslation()
  return (
    <div className="flex flex-col items-center justify-center py-16 px-4">
      {illustration ? (
        <img
          src={illustration}
          alt=""
          aria-hidden="true"
          className="empty-illustration mb-5 h-40 w-40 select-none"
        />
      ) : (
        <div className="text-[var(--color-text-tertiary)] mb-4">
          {icon || <FileText size={48} />}
        </div>
      )}
      <p className="text-sm text-[var(--color-text-secondary)] mb-4">
        {message || t('note.empty')}
      </p>
      {action}
    </div>
  )
}
