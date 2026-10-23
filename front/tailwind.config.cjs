/** @type {import('tailwindcss').Config} */
// 说明：运行时配色以 src/index.css 的 CSS 变量为准，这里只是同一套灰阶的镜像，
// 供少数直接写 Tailwind 类名的场景使用。任何新增颜色都必须是无彩灰阶。
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        heading: ['Noto Serif SC', 'Songti SC', 'serif'],
        body: ['Noto Sans SC', 'PingFang SC', 'SF Pro Display', 'Helvetica Neue', 'sans-serif'],
        mono: ['JetBrains Mono', 'SF Mono', 'Consolas', 'monospace'],
      },
      colors: {
        bg: {
          DEFAULT: '#F2F2F2',
          secondary: '#E9E9E9',
          tertiary: '#DEDEDE',
        },
        card: {
          DEFAULT: '#FFFFFF',
          hover: '#F7F7F7',
        },
        text: {
          DEFAULT: '#0A0A0A',
          secondary: '#5A5A5A',
          tertiary: '#828282',
          placeholder: '#B8B8B8',
        },
        border: {
          DEFAULT: '#D6D6D6',
          light: '#E8E8E8',
        },
        divider: '#E4E4E4',
        accent: {
          DEFAULT: '#0A0A0A',
          hover: '#2B2B2B',
          bg: '#E6E6E6',
          contrast: '#FFFFFF',
        },
        success: {
          DEFAULT: '#444444',
          bg: '#ECECEC',
        },
        danger: {
          DEFAULT: '#0A0A0A',
          bg: '#D2D2D2',
        },
        warning: {
          DEFAULT: '#5A5A5A',
          bg: '#F0F0F0',
        },
      },
      spacing: {
        xs: '4px',
        sm: '8px',
        md: '16px',
        lg: '24px',
        xl: '32px',
        '2xl': '48px',
        '3xl': '64px',
      },
      borderRadius: {
        sm: '2px',
        md: '4px',
        lg: '6px',
        xl: '8px',
        '2xl': '10px',
      },
      lineHeight: {
        tight: '1.3',
        normal: '1.6',
        loose: '1.8',
      },
    },
  },
  plugins: [require('@tailwindcss/typography')],
}
