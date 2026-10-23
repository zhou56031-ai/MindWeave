interface BrandMarkProps {
  /** 边长（px）。24 的整数倍缩放时线条最锐利。 */
  size?: number
  className?: string
}

/**
 * 品牌标记：3×3 织格 + 一格实心。
 * 用 currentColor 绘制，跟随所在位置的文字颜色，因此浅色/深色主题共用一份。
 */
export default function BrandMark({ size = 22, className = '' }: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <path
        d="M3 3h18M3 9h18M3 15h18M3 21h18M3 3v18M9 3v18M15 3v18M21 3v18"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="square"
        shapeRendering="crispEdges"
      />
      <rect x="15" y="15" width="6" height="6" fill="currentColor" />
    </svg>
  )
}
