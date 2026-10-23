import { Outlet } from 'react-router-dom'

export default function AuthLayout() {
  return (
    <div className="relative min-h-screen flex items-center justify-center overflow-hidden bg-[var(--color-bg)]">
      {/* 极淡织格：只在留白处出现，边缘径向淡出，不抢表单 */}
      <div className="grid-backdrop pointer-events-none absolute inset-0" aria-hidden="true" />
      <div className="relative w-full max-w-md mx-auto p-8">
        <Outlet />
      </div>
    </div>
  )
}
