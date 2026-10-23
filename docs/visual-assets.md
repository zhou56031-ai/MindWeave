# 视觉资产清单与生成提示词

> 承接 [设计系统](design-system.md)：整套界面只有一条明度轴，**新增的任何视觉元素也必须是纯黑白线稿**。
> 本文回答三件事：需要哪些图、每张图放在哪、每张图怎么生成（可直接复制的提示词）。

> **当前进度（2026-10-22）**：1、3、5 以及登录背景已经**手绘落地**，文件在
> `front/public/brand/` 与 `front/public/illustrations/`，接入见 [设计系统](design-system.md#6-图形资产)。
> OG 图（#6）与 README Banner（#7）也已落地：`front/public/brand/og.png`、`docs/images/banner.png`。
> 仍待补齐：图谱空态网格（#8，也可用 CSS 网格代替）。

---

## 0. 先说结论：哪些该用 AI，哪些不该

| 资产 | 建议 | 原因 |
|---|---|---|
| Logo 图形标记 | **手写 SVG**（AI 只用来出概念草图） | 几何精度要求高，AI 生成的是位图，边缘和对称性不可控 |
| Logo 里的字（织识 / MindWeave） | **排版生成**，绝不交给 AI | 生成模型写中文字必糊，且字距无法控制 |
| Favicon / App Icon | 由 Logo 标记导出 PNG | 同一份形状，多尺寸导出即可 |
| 空状态插图 ×5 | **AI 生成 + 二值化** | 这类图允许一点"手绘感"，AI 效率最高 |
| 登录页装饰 / 图谱背景 | AI 生成 + 二值化 | 需要疏松的线稿，AI 擅长 |
| OG 分享图 / README Banner | 生成底纹 + 后期排版文字 | 文字部分必须自己排 |
| UI 图标（导航、按钮） | **继续用 lucide-react** | 已有 40+ 个统一图标，AI 生成会破坏一致性 |
| 加载动画 | 用 CSS/SVG 动画 | 位图做不了循环动画 |

**一句话**：AI 负责"画形状和氛围"，你负责"保证它只有两种颜色、边缘干净、没有字"。

---

## 1. 现有产品结构与落点

先看清楚这些图要贴到哪，提示词才有意义。

| 位置 | 现状 | 可加入的视觉元素 |
|---|---|---|
| 侧边栏顶部（`components/layout/Sidebar.tsx`） | 只有文字 `织识` | 20–24px 的图形标记 + 文字锁定组合 |
| 登录页（`pages/Login.tsx`） | 居中标题 + 表单，大量留白 | 标题上方 48–64px 标记，或右侧 30% 淡线稿 |
| 空状态（`components/common/EmptyState.tsx`） | lucide 48px 图标 | 5 张 1:1 插图（笔记/知识库/会话/回顾/图谱） |
| 图谱页空态（`pages/GraphPage.tsx`） | 图标 + 文案 | 网格或节点线稿作背景 |
| 关于页（`pages/AboutUs.tsx`） | 纯文字 + 技术栈标签 | 一张横向插画或锁定组合 |
| `index.html` | 已用单色 `favicon.svg` | 补齐 512/192/180 的 PNG |
| README | 设计板截图 | 顶部 Banner + OG 图 |

---

## 2. 资产清单

| # | 资产 | 尺寸 / 格式 | 数量 | 优先级 | 落地路径 |
|---|---|---|---|---|---|
| 1 | Logo 图形标记 | SVG（24×24 视框） | 1 | P0 | `front/public/brand/mark.svg` |
| 2 | 完整锁定组合（标记+中英文字） | SVG | 1 | P0 | `front/public/brand/lockup.svg` |
| 3 | App Icon | PNG 512/192 + 180(apple) | 3 | P0 | `front/public/brand/` |
| 4 | 登录页装饰 | PNG/WebP 1200×1600（竖） | 1（可双主题各一） | P0 | `front/src/assets/login-motif.png` |
| 5 | 空状态插图 | PNG/WebP 1024×1024，透明 | 5 | P0 | `front/src/assets/empty/*.png` |
| 6 | OG 分享图 | PNG 1200×630 | 1 | P1 | `front/public/brand/og.png` |
| 7 | README Banner | PNG 1600×400 | 1 | P1 | `docs/images/banner.png` |
| 8 | 图谱空态背景 | SVG/PNG 1600×900 | 1 | P2 | `front/src/assets/graph-grid.svg` |
| 9 | 文档类型缩略图（PDF/DOCX/PPTX/MD） | SVG 4 个 | 4 | P2 | `front/src/assets/file-types/` |
| 10 | 关于页插画 | PNG 1600×800 | 1 | P2 | `front/src/assets/about.png` |

> **不要**给 1、2、9 用 AI 生成结果直接上生产：位图缩放会糊，而且线条粗细不一致。

---

## 3. 通用风格前缀（关键：所有图共用这一段）

生成任何一张图之前，都先拼上这段。它是"整套图看起来像一家人"的唯一保证。

```text
STYLE PREFIX
pure monochrome, black ink on pure white, uniform 1.5px hairline strokes,
geometric line art, Swiss editorial minimalism, flat vector aesthetic,
generous negative space, centered composition, no shading, no fill except
one single solid black accent shape, crisp edges, high contrast,
isolated on plain white background
```

```text
NEGATIVE PROMPT
color, colored, red, blue, gradient, color gradient, glow, neon, shadow,
drop shadow, 3d render, isometric, perspective, glossy, metallic, texture,
paper texture, noise, grain, halftone, sketchy lines, rough pencil,
handwritten, calligraphy, ornate, decorative, floral, cartoon, mascot,
emoji, face, text, letters, words, typography, watermark, signature,
border, frame, vignette, clutter, busy, low contrast, blurry, jpeg artifacts
```

参数建议：

| 工具 | 参数 |
|---|---|
| Midjourney | `--ar 1:1 --style raw --no color,text,gradient,shadow` + 上面负向词 |
| Flux / SDXL | 1024×1024，20–30 steps，CFG 3.5–5，采样器 DPM++ 2M 或 Euler |
| DALL·E 3 / 即梦 / 可灵 | 直接把风格前缀和负向词都写进中文或英文句子 |
| 通用 | 一次生成 4 张挑 1 张；**同一批任务用同一个 seed**，风格更稳 |

---

## 4. 逐个提示词

### 4.1 Logo 图形标记（三个方向，选一个）

**方向 A：织格（grid / weave）——与现有 favicon 一致，最稳**

```text
A minimal geometric logo mark: a 3x3 lattice made of nine equal cells drawn with
uniform hairline strokes, three horizontal and three vertical lines crossing at
right angles, with exactly one cell in the lower right filled solid black,
perfectly square and symmetrical, centered with equal margins,
pure monochrome black line art on white, no text, no circle, no border

--ar 1:1 --style raw --no color,text,gradient,shadow,rounded corners
```

**方向 B：折线 W（把 MindWeave 的首字母折成织线）**

```text
A minimal geometric monogram: a single continuous sharp polyline forming a
zigzag "W" with four straight segments at consistent 60-degree angles,
the line weight uniform and thin, ends squared, no curves, one segment
slightly thicker in solid black as an accent, centered on white,
flat vector, no text, no circle

--ar 1:1 --style raw --no color,text,gradient,shadow
```

**方向 C：交织双环（两条线互相穿过一次，像织布）**

```text
A minimal line-art mark: two identical thin square frames rotated 45 degrees,
overlapping so their edges interlace once at the center like woven threads,
one short segment in solid black showing the over-under crossing,
otherwise pure hairline strokes, perfectly symmetrical, centered, white background,
no text, no shading

--ar 1:1 --style raw --no color,text,gradient,shadow
```

> 拿到满意的形状后，**不要直接用图**：用 Illustrator/Figma 的 Image Trace 或 `vtracer` 转成路径，再手动对齐到 24×24 网格、统一 1.5px 描边，导出 SVG。

---

### 4.2 登录页装饰（竖构图，放在右侧或作背景）

```text
A tall sparse architectural line drawing: a vertical lattice of thin horizontal
shelves and three vertical threads, each shelf holding one small square block,
one block filled solid black, the composition aligned to an invisible grid,
huge empty white space at the top and bottom, calm and quiet,
pure monochrome hairline line art, no text, no shading, no perspective

--ar 3:4 --style raw --no color,text,gradient,shadow,texture
```

用法建议：放在登录表单右侧，宽 40%，`opacity: 0.10–0.16`；深色主题下用 CSS `filter: invert(1)`，不要单独生成一张深色版。

---

### 4.3 空状态插图 ×5（统一 1:1，透明背景）

**笔记为空**

```text
A minimal line illustration of three stacked rectangular sheets, slightly offset,
each outlined with a single hairline, the top sheet showing two horizontal
hairline rules as abstract writing lines, one small solid black square in the
corner of the top sheet, centered composition, lots of white space around,
flat vector line art, monochrome, no text

--ar 1:1 --style raw --no color,text,gradient,shadow
```

**知识库为空**

```text
A minimal line illustration of an open folder seen from the front, one page
rising out of it, the page crossed by a 3x3 hairline grid, the folder tab as a
single straight line, one small solid black circle at the page corner,
symmetrical, centered, white background, flat monochrome line art, no text

--ar 1:1 --style raw --no color,text,gradient,shadow
```

**会话为空**

```text
A minimal line illustration of two overlapping square speech bubbles with sharp
corners, no rounded cartoon style, each outlined with a hairline, the front one
containing three short horizontal hairline rules, the back one empty,
one small solid black triangle as the tail, centered, generous white space,
flat monochrome line art, no text

--ar 1:1 --style raw --no color,text,gradient,shadow
```

**回顾为空（每日复习没有到期内容）**

```text
A minimal line illustration of a monthly calendar grid drawn as 7 columns and
4 rows of hairline squares, exactly one cell filled solid black, a single short
hairline underline beneath the filled cell, no numbers, no letters,
centered, calm composition, flat monochrome line art, white background

--ar 1:1 --style raw --no color,text,numbers,gradient,shadow
```

**图谱为空**

```text
A minimal network diagram: five small circles of identical size connected by
straight hairlines, one circle isolated at the edge without any connection,
one circle slightly filled solid black, nodes arranged on a loose hexagonal
grid, lots of empty space, flat monochrome line art, no text, no labels

--ar 1:1 --style raw --no color,text,gradient,shadow
```

---

### 4.4 App Icon / Favicon（512）

```text
An app icon: a perfect square canvas, a black 3x3 lattice of hairlines inset
with equal padding from all four edges, exactly one cell filled solid black,
crisp right angles, no rounded corners, no border, no text, centered,
high contrast pure black and white, flat vector

--ar 1:1 --style raw --no color,text,gradient,shadow,rounded
```

> 更省事的做法：直接拿 4.1 选中的 SVG，在 Figma 里放到 512×512 画板居中导出 PNG。**这比生成更准。**

---

### 4.5 OG 分享图 / README Banner（生成底纹，文字自己排）

```text
A wide abstract composition: a sparse lattice of thin horizontal and vertical
lines fading out toward the left and right edges, like a woven grid dissolving
into white, one small solid black square near the right third, vast white space
in the center-left for text, extremely minimal, pure monochrome hairline art,
no text, no logo, no border

--ar 16:9 --style raw --no color,text,gradient,shadow
```

后期在 Figma 里排版：

```
左侧：织识（Noto Serif SC Bold 72–96px）+ MindWeave（Noto Sans SC 32px, 字距 0.08em）
副标题：把笔记、文档与知识图谱织成一张网（Noto Sans SC 28px, #5A5A5A）
右下角：三行小字（GitHub / 版本 / 日期），11px，字距 0.14em，全大写
```

---

### 4.6 图谱空态背景（可选）

```text
A seamless faint grid of 1px lines, 32px cells, pure black lines on white,
no dots, no shading, perfectly uniform, top-down flat, no perspective,
subtle and low contrast, no text

--ar 16:9 --style raw --no color,text,gradient
```

用法：`opacity: 0.06`，`background-size: 32px 32px`。若嫌麻烦，直接用 CSS `repeating-linear-gradient` 画网格更轻，不必生成。

---

### 4.7 文档类型缩略图（可选，4 个）

```text
A minimal file-type icon: a rectangular page with a folded corner, outlined with
a single hairline, containing a 2x2 grid of small hairline squares in the middle,
one square filled solid black, no letters, no text, flat monochrome line art,
centered, white background

--ar 1:1 --style raw --no color,text,letters,gradient,shadow
```

四张只在"内部图案"上区分：PDF 用两条横线、DOCX 用三条短横线、PPTX 用两个叠放方块、MD 用一个 `#` 形状的纯几何符号（不要真的写字）。

---

### 4.8 关于页插画（可选）

```text
A horizontal minimal line illustration: three vertical threads on the left,
three horizontal threads on the right, meeting in the middle to form a single
woven square, a few threads extending beyond the square and ending abruptly,
huge white margins on both sides, pure monochrome hairline line art, no text,
no gradient

--ar 2:1 --style raw --no color,text,gradient,shadow
```

---

## 5. 后处理：把生成图变成"能用"的图

生成出来的图几乎一定带灰阶、脏边、噪点。三步处理：

**① 二值化（只留纯黑与纯白）**

```bash
# macOS 需要先：brew install imagemagick
magick input.png -colorspace Gray -threshold 72% -resize 1024x1024 output.png
```

阈值 65%–78% 之间多试几次——太高线条会断，太低线条会糊。

**② 矢量化（需要 SVG 时）**

```bash
# brew install vtracer
vtracer --input output.png --output output.svg --mode spline --colormode binary --filter_speckle 8
```

矢量化之后一定要手动检查：尖角是否变圆、两条线是否粘连、对称是否歪 1–2px。

**③ 统一到设计令牌**

- 描边色：`#0A0A0A`（浅色）/ 通过 `filter: invert(1)` 适配深色；
- SVG 内的 `stroke` 与 `fill` 改成 `currentColor`，让它自动跟随文字颜色；
- 一张图最多一个实心块，否则视觉上会"变重"，破坏极简。

---

## 6. 落地清单（生成完照着改）

| 动作 | 文件 | 说明 |
|---|---|---|
| 放入标记 | `front/public/brand/mark.svg` | 用 `currentColor`，24×24 视框 |
| 侧边栏加标记 | `components/layout/Sidebar.tsx:57-61` | 文字前加 22px 图标，`gap-2`，折叠时只显示图标 |
| 登录页加标记 | `pages/Login.tsx` 标题上方 | 56px，`opacity: .9`，下方留 20px |
| 空状态换插图 | `components/common/EmptyState.tsx` | 新增可选 `illustration?: string`，优先于 `icon` |
| 替换旧图标 | 已换为 `front/public/brand/icon-512.png` | 旧的 776 KB 彩色 `icon.png` 已删除 |
| 补 favicon | `index.html` | 增加 `apple-touch-icon` 与 32px PNG 兜底 |
| OG 标签 | `index.html` | `og:image`、`og:title`、`og:description` |
| README Banner | `docs/images/banner.png` | 放在标题下方 |

---

## 7. 验收：怎么判断"好看"而不是"变花"

- [ ] 缩到 24px 还认得出来吗（Logo 的最小尺寸测试）？
- [ ] 转成灰度后，图里是否**只有两种颜色**（没有灰边）？
- [ ] 深色主题下 `invert()` 之后，是否还有不该出现的实心块？
- [ ] 插图和正文留白相比，是否"轻到可以忽略"（空状态不该抢眼）？
- [ ] 五张空状态放在一起，线条粗细和圆角风格是否一致？
- [ ] 有没有任何一个元素引入了新的颜色、渐变、阴影？

---

## 8. 我的建议

1. **Logo 先做三个方向的黑白草稿**（用 4.1 的提示词），选一个手工转 SVG——这一步不要省。
2. **五张空状态统一用同一批参数生成**，否则五张图像五个产品。
3. 登录页装饰只放一张、透明度压到 0.12 以下，宁可"几乎看不见"。
4. OG 与 Banner 只做一次，之后所有平台复用。
5. 如果某张图始终不满意，**优先用纯 CSS/几何 SVG 画**——在只有直线的黑白体系里，手画的往往比生成的干净。
