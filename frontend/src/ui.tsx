import type { ReactNode } from 'react'

// 共享小组件：卡片、按钮、标签、估算提示，统一各功能面板风格。

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-slate-200 bg-white p-5 ${className}`}>{children}</div>
  )
}

export function Button({
  children,
  onClick,
  disabled,
  variant = 'primary',
  type = 'button',
}: {
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  variant?: 'primary' | 'ghost' | 'danger'
  type?: 'button' | 'submit'
}) {
  const styles = {
    primary: 'bg-slate-900 text-white hover:bg-slate-700 disabled:bg-slate-300',
    ghost: 'border border-slate-300 text-slate-700 hover:bg-slate-100 disabled:opacity-50',
    danger: 'bg-rose-600 text-white hover:bg-rose-500 disabled:bg-slate-300',
  }[variant]
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-md px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${styles}`}
    >
      {children}
    </button>
  )
}

export function Estimated() {
  // AI 估算标注（07 可信度风险：UI 须明示）。
  return (
    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-700">AI 估算 · 仅供参考</span>
  )
}

export function ErrorNote({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <p className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">{message}</p>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-slate-300 border-t-slate-600" />
      {label ?? '处理中…'}
    </span>
  )
}
