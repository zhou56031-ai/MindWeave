# 织识 MindWeave · 前端

React 19 + Vite + Tailwind 的前端，源码沿用上游项目 [RMA-MUN/RAGNotebook](https://github.com/RMA-MUN/RAGNotebook)
提交 `7445eb3`（MIT），只做了三处适配：

1. 开发端口改为 `3100`，`/user`、`/note` 等请求代理到 `http://127.0.0.1:8100`；
2. 配合后端 SSE 事件约定（阶段 / 工具 / 证据 / 答案 / 审批）；
3. 品牌文案改为「织识 MindWeave」；
4. 配色改为黑白单色：令牌集中在 `src/index.css`，规则见 [设计系统](../docs/design-system.md)。

```bash
npm ci
npm run dev -- --host 127.0.0.1 --port 3100   # 需同时启动后端、MySQL、Redis 与图谱 Worker
npm run build                                  # tsc + vite 生产构建
npm run lint
```

`http://127.0.0.1:3100/health/ready` 可确认前端代理是否抵达后端。
功能与接口全景见 [docs/AI-Agent功能全景说明.md](../docs/AI-Agent功能全景说明.md)。
