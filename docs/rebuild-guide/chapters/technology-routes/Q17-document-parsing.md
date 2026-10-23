# Q17：PDF、DOCX、PPTX 解析路线

## 1. 原理与本项目的使用

第 37 篇的目标不是“把文件扩展名换成 txt”，而是把不同文档还原为带页号或段落顺序的正文。PDF 的文字层由 PyMuPDF 按页提取；DOCX 的段落与表格由 python-docx 按正文顺序遍历；PPTX 的幻灯片文字形状与表格由 python-pptx 读取。合并单元格、嵌套结构、备注和复杂视觉顺序仍可能丢失，不能把当前解析结果称为完整保真。文字抽取可能改变阅读顺序，表格的行列关系也可能丢失，所以解析结果应保存来源文件、页码与切片序号，让人能回到原文核对。[PyMuPDF 页面文字](https://pymupdf.readthedocs.io/en/latest/page.html)、[python-docx 指南](https://python-docx.readthedocs.io/en/latest/user/quickstart.html)、[python-pptx 形状说明](https://python-pptx.readthedocs.io/en/latest/user/understanding-shapes.html)。

## 2. 同类技术路线对比

| 路线 | 适合的情况 | 代价或边界 |
|---|---|---|
| 按格式专用库 | 本教程采用；依赖少、行为可逐格式解释 | 需要自己处理表格、页码和异常 |
| LibreOffice 转 PDF/文本 | 版式还原需求高时可用 | 需要额外进程、转换失败与资源隔离 |
| Apache Tika/通用解析服务 | 格式很多时统一入口 | 服务运维成本增加，输出结构仍需校验 |
| 只按扩展名读取 UTF-8 | 仅限 TXT/MD | 二进制 Office/PDF 会乱码或失败 |

## 3. 工程边界与面试追问

导入先限制文件大小和允许格式，再识别实际内容；不应因为文件叫 .pdf 就相信它一定是 PDF。每种格式保留页/段来源，解析为空要分辨“扫描页只有图”和“损坏文件”。面试官若问为什么不用一个万能库，回答应包括可控性、格式特性、错误隔离和后续排查成本。第 38 篇才处理扫描页与图片；纯文本解析无法读出像素里的字。

