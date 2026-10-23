/**
 * 黑白主题下的实体类型取色。
 *
 * 后端为实体类型存了彩色值（历史数据），但当前设计只允许无彩灰阶，
 * 所以前端按类型 ID 的哈希在同一条明度轴上取一档，保证：
 *   1. 同一类型在任何页面、任何时间都得到同一个灰阶；
 *   2. 浅色主题用深灰、深色主题用浅灰，始终与画布有足够对比。
 *
 * 注意：不同 ID 可能撞到同一档，这是可接受的——节点形状与大小仍能区分类型。
 */
const RAMP_LIGHT = ['#111111', '#333333', '#4F4F4F', '#6B6B6B', '#878787', '#A3A3A3']
const RAMP_DARK = ['#F2F2F2', '#D6D6D6', '#B8B8B8', '#9A9A9A', '#7C7C7C', '#5E5E5E']

export type MonoTheme = 'light' | 'dark'

export function monoShade(seed: string, theme: MonoTheme): string {
  let hash = 0
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0
  }
  const ramp = theme === 'dark' ? RAMP_DARK : RAMP_LIGHT
  return ramp[hash % ramp.length]
}
