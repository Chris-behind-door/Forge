# 工程设计工作台 - 技术方案文档

> 版本: 4.0
> 日期: 2026-04-24
> 作者: 克里斯 + 小爪
> 许可证: 开源（待定）

---

## 1. 项目概述

### 1.1 背景

工程设计领域存在大量技术资料和会议纪要，从业者需要：
- 快速查询技术规范
- 追溯会议决议及其变更历史
- 验证信息来源

### 1.2 核心功能

1. **技术资料 RAG** - 知识库检索 + 引用溯源
2. **BYOK** - 用户自带 API Key，支持多个 LLM 厂商
3. **会议纪要关联** - 图数据库追踪决议演变链（SUPERSEDES/AMENDS/SUPPLEMENTS）
4. **异步导入队列** - 后台串行处理，前端即时响应 + 状态追踪

> ~~分流智能体~~ 已取消，由主 Agent 自行判断查询对象

### 1.3 目标用户

- 工程设计从业者
- 非技术背景为主
- 需要跨平台（macOS/Windows/Linux）

### 1.4 开源策略

本项目采用开源模式 + BYOK（Bring Your Own Key）：
- 用户自行配置 LLM API Key（智谱/DeepSeek/通义/Ollama 等）
- 无中转服务器，不存储用户 Key（使用系统密钥链）
- 所有数据处理在本地完成，不上传任何文档到云端
- Embedding 使用本地模型（fastembed + bge-small-zh），无需 API Key

---

## 2. 技术栈选型

### 2.1 桌面框架: Tauri 2.0

**选型理由**
- 体积小（<600KB），使用系统原生 WebView
- 跨平台: macOS / Windows / Linux
- 安全性: 经过安全审计
- 支持 Sidecar: 可嵌入 Python 后端

**备选方案:** Electron（体积 150MB+，排除）

### 2.2 前端: React + Vite + Ant Design

**选型理由**
- React 生态成熟
- Vite 构建快速
- Ant Design 组件丰富，适合桌面应用风格

### 2.3 后端: FastAPI

**选型理由**
- 异步支持，性能好
- 自动生成 API 文档
- Python 原生，与 RAG 生态兼容

### 2.4 打包: PyInstaller

**选型理由**
- 支持 Python 3.14
- 兼容性好，社区成熟
- 打包为单可执行文件

### 2.5 包管理: uv

**选型理由**
- 10-100x 比 pip 快
- 一站式管理: pip + pipx + poetry + pyenv
- Rust 实现，跨平台

### 2.6 RAG 框架: LlamaIndex + Workflow

**选型理由**
- `ParentDocumentRetriever` 内置父子切片
- Workflow 支持事件驱动、循环、分支
- 有现成的 Citation Query Engine 示例

**Workflow 架构（已实现）:**

```
StartEvent
    ↓
ToolCallStep (LLM + 工具调用循环，最多 3 轮)
    ↓
ExpandContextStep (检索 chunk 前后各 1 chunk 扩展上下文)
    ↓
GenerateStep (注入扩展上下文，生成带引用的回答)
    ↓
StopEvent
```

### 2.7 向量库: LanceDB

**选型理由**
- 嵌入式，无需服务器
- 多模态支持（向量 + 全文 + SQL + 混合搜索）
- 性能好（列式存储）
- LlamaIndex 原生集成

### 2.8 图数据库: Kùzu

**选型理由**
- **MIT 许可证**（Neo4j 是 GPL，商业分发受限）
- 原生嵌入式设计
- 支持 Cypher 查询语言
- 内置向量索引
- 体积小（~20MB vs Neo4j ~100MB+）

**注意:** Kùzu 项目已归档，但 0.11.3 版本稳定可用

**图模型:**

```
Project ──CONTAINS_MEETING──▶ Meeting ──CONTAINS_RESOLUTION──▶ Resolution
                                                                  │
                            SUPERSEDES ◀─────────────────────────┘
                            AMENDS ◀─────────────────────────────┘
                            SUPPLEMENTS ◀────────────────────────┘
```

- Meeting 节点: id, project_id, title, date, summary, source_doc_id, raw_text, created_at, status, error
- Resolution 节点: id, meeting_id, project_id, content, idx, status, source_doc_id, created_at, embedding
- 关系: SUPERSEDES/AMENDS/SUPPLEMENTS (Resolution → Resolution, 含 meeting_id, reason 等属性)
- Schema 版本管理: `schema_version.txt`，ALTER TABLE 迁移

### 2.9 文档解析: PyMuPDF + RapidOCR

**已实现：**
- PyMuPDF 直接提取 PDF 文字
- RapidOCR (ONNX Runtime) 处理扫描件
- 线程池并行 OCR
- CHM 解析（7z 解压 + HTML 文本提取）

**备选（未实现）：** Docling（高级 PDF 能力：表格、公式、代码、图表、多格式 DOCX/PPTX/HTML/OCR）

### 2.10 Embedding 模型: fastembed + bge-small-zh

**已实现：**
- 本地 ONNX Runtime，离线模式
- BAAI/bge-small-zh-v1.5（512 维）
- 无需 API Key，无需 GPU

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    工程设计工作台                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Tauri 2.0 (Rust)                                    │   │
│  │  ├── WebView (系统原生)                              │   │
│  │  └── Sidecar ───────────────────────────────────┐   │   │
│  └─────────────────────────────────────────────────│───┘   │
│                                                    │       │
│  ┌─────────────────────────────────────────────────│───┐   │
│  │  前端 (React + Vite + Ant Design)                │   │   │
│  │  ├── 资料导入 / 知识库管理                        │   │   │
│  │  ├── 会议纪要管理 (Timeline + 关联图)             │   │   │
│  │  ├── 查询界面 (Markdown + 引用标签)               │   │   │
│  │  └── 设置（API Key 配置）                        │   │   │
│  └─────────────────────────────────────────────────│───┘   │
│                                                    │       │
│  ┌─────────────────────────────────────────────────│───┐   │
│  │  后端 (FastAPI)  ◄──────────────────────────────┘   │   │
│  │                                                     │   │
│  │  routers/          services/          graph/        │   │
│  │  ├── meetings.py   ├── meeting_service.py           │   │
│  │  ├── documents.py  ├── resolution_service.py        │   │
│  │  ├── sessions.py   ├── document_service.py          │   │
│  │  ├── config.py     ├── import_worker.py             │   │
│  │  └── projects.py   ├── chm_service.py               │   │
│  │                     └── json_store.py               │   │
│  │                                                     │   │
│  │  ┌─────────────┐  ┌──────────┐  ┌───────────────┐  │   │
│  │  │ LanceDB     │  │ Kùzu     │  │ JSON Store    │  │   │
│  │  │ (向量检索)   │  │ (图关联)  │  │ (会议/决议)   │  │   │
│  │  └─────────────┘  └──────────┘  └───────────────┘  │   │
│  │                                                     │   │
│  │  导入队列: asyncio.Queue + 串行 worker              │   │
│  │  文档解析: PDF/CHM/DOCX → OCR → 文本                │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  数据存储  ~/.engineer_assistant/data/               │   │
│  │  ├── uploads/           # 上传的文档                 │   │
│  │  ├── vectors/           # LanceDB 向量数据           │   │
│  │  ├── graph.db           # Kùzu 图数据库              │   │
│  │  ├── meetings.json      # 会议记录                   │   │
│  │  ├── resolutions.json   # 决议记录                   │   │
│  │  ├── documents.json     # 文档元数据                 │   │
│  │  ├── import_staging/    # 导入临时文件（持久化）      │   │
│  │  └── schema_version.txt # Kùzu schema 版本          │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. 核心模块设计

### 4.1 后端分层架构

后端采用 **Router + Service** 分层：

- **Router 层** (`src/routers/`)：纯 HTTP 处理，参数校验，调用 service
- **Service 层** (`src/services/`)：业务逻辑，数据读写，图查询
- **Graph 层** (`src/graph/`)：Kùzu 连接管理，schema 初始化，Cypher 查询封装

| Service | 职责 |
|---------|------|
| `meeting_service.py` | 会议 CRUD、文件导入、决议重新提取 |
| `resolution_service.py` | 决议 CRUD、批量创建关联、孤儿 superseded 恢复 |
| `document_service.py` | 文档管理、断点恢复 |
| `import_worker.py` | 异步导入队列（asyncio.Queue + 串行 worker） |
| `chm_service.py` | CHM 文件解析 |
| `json_store.py` | 通用 JSON 文件读写 |

### 4.2 导入队列

**架构：**
```
前端上传 → POST /import → 创建会议(status=queued) + 文件存 staging → 入队
                                                                       ↓
前端轮询 ← GET /import-status ← ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   worker 串行处理
                                                     文本提取(线程池) → LLM提取决议 → 创建关联
```

**状态流转：**
```
queued → processing → active (成功)
                   → failed  (失败，可重试)
```

**关键设计：**
- 串行处理确保跨会议关联（SUPERSEDES）正确构建
- OCR 跑在 `asyncio.to_thread` 避免阻塞事件循环
- staging 文件存到 `import_staging/` 目录，服务重启后可重试
- 启动时自动将残留的 processing/queued 会议标记为 failed
- 删除 processing 会议时发送 cancel 信号，worker 在检查点停止

### 4.3 LLM 配置管理 (BYOK)

**设计原则：**
- 用户自行配置 API Key，应用不提供任何内置 Key
- Key 存储在系统密钥链（keyring），不明文保存
- 支持多个 LLM 厂商，用户可随时切换

| 厂商 | API Base | 备注 |
|------|----------|------|
| 智谱 GLM | https://open.bigmodel.cn/api/paas/v4 | 默认推荐 |
| DeepSeek | https://api.deepseek.com/v1 | 性价比高 |
| 阿里通义 | https://dashscope.aliyuncs.com/compatible-mode/v1 | |
| Ollama | http://localhost:11434/v1 | 本地部署，完全离线 |
| 自定义 | 用户填写 | 任意 OpenAI 兼容 API |

### 4.4 RAG 检索 (Retriever)

**已实现：**
- fastembed bge-small-zh embedding（离线）
- LanceDB 向量存储
- 混合检索（向量语义 + 关键词匹配）
- PDF 解析（直接提取 + OCR fallback + 并行）
- CHM 解析（7z + HTML 文本提取）
- Chunk 上下文扩展（检索后前后各 1 chunk，去重后注入 LLM prompt）

### 4.5 会议纪要关联 ✅ 已实现

**图模型节点和边：**
- Meeting: id, project_id, title, date, summary, status(active/processing/queued/failed), error
- Resolution: id, meeting_id, project_id, content, idx, status(active/superseded/amended), embedding
- SUPERSEDES: Resolution → Resolution（新决议取代旧决议）
- AMENDS: Resolution → Resolution（修正）
- SUPPLEMENTS: Resolution → Resolution（补充）

**决议状态管理：**
- 删除会议时级联删除决议，同时恢复被 SUPERSEDED 但无其他引用的决议为 active
- 删除单条决议同理
- 批量创建时自动检测跨会议关联（时间双向匹配 + LLM 语义判断）

**前端展示：**
- Timeline 组件展示会议时间线
- 决议卡片显示关联链（SUPERSEDES/AMENDS/SUPPLEMENTS），可点击跳转
- 关联图可视化

### 4.6 前端组件结构

```
MeetingsView (主布局)
├── MeetingList (左侧时间线)
│   └── MeetingStatusBadge (状态徽章)
├── MeetingDetail (右侧详情)
│   ├── ResolutionCard (决议卡片)
│   └── RelationItem (关联链)
└── ImportMeetingModal (导入弹窗)

KnowledgeBaseView (主布局)
├── ProjectSelector (项目选择)
├── DocumentList (文档列表)
└── DocumentViewer (文档预览)
```

---

## 5. 端口与进程管理

### 5.1 端口动态分配

- Tauri 侧: `find_available_port(base_port=8765)` 尝试绑定
- 环境变量: `FORGE_PORT`、`FORGE_HOST` 可覆盖
- 前端通过 Tauri IPC 获取实际端口

### 5.2 前后端通信

前端通过 Tauri event 获取后端端口。无 IPC 鉴权（本地应用）。

---

## 6. 目录结构

```
engineer_assistant/
├── backend/
│   ├── src/
│   │   ├── main.py                 # FastAPI 入口 + startup
│   │   ├── routers/
│   │   │   ├── meetings.py         # 会议/决议/关联 API
│   │   │   ├── documents.py        # 文档管理 API
│   │   │   ├── sessions.py         # 会话管理
│   │   │   ├── config.py           # LLM 配置
│   │   │   └── projects.py         # 项目管理
│   │   ├── services/
│   │   │   ├── meeting_service.py  # 会议 CRUD + 导入
│   │   │   ├── resolution_service.py # 决议 CRUD + 关联
│   │   │   ├── document_service.py # 文档处理 + 断点恢复
│   │   │   ├── import_worker.py    # 异步导入队列
│   │   │   ├── chm_service.py      # CHM 解析
│   │   │   └── json_store.py       # 通用 JSON 读写
│   │   ├── graph/
│   │   │   ├── db.py               # Kùzu 连接 + schema 迁移
│   │   │   ├── queries.py          # Cypher 查询封装
│   │   │   └── extract.py          # LLM 决议提取
│   │   ├── llm/
│   │   │   ├── agent.py            # Agent 入口
│   │   │   ├── client.py           # LLM API 调用
│   │   │   ├── prompts.py          # System prompt
│   │   │   ├── tools.py            # Agent 工具
│   │   │   └── workflow.py         # LlamaIndex Workflow
│   │   ├── rag/
│   │   │   ├── embeddings.py       # fastembed
│   │   │   └── vector_store.py     # LanceDB
│   │   ├── parsers/
│   │   │   ├── pdf.py              # PyMuPDF + OCR
│   │   │   └── chm.py              # CHM 解析
│   │   ├── models/
│   │   │   ├── meeting.py          # Pydantic 模型
│   │   │   └── session.py          # 会话持久化
│   │   └── utils/
│   │       ├── paths.py            # 路径 + schema 版本
│   │       └── llm_config.py       # LLM 配置 + keyring
│   ├── tests/
│   │   └── test_api.py             # pytest 单元测试 (59 个)
│   ├── pyproject.toml
│   └── build.spec
│
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   ├── views/
│   │   │   ├── MeetingsView.tsx    # 会议纪要主视图
│   │   │   └── KnowledgeBaseView.tsx # 知识库主视图
│   │   ├── components/
│   │   │   ├── MeetingList.tsx     # 会议时间线
│   │   │   ├── MeetingDetail.tsx   # 会议详情 + 决议
│   │   │   ├── ResolutionCard.tsx  # 决议卡片
│   │   │   ├── ImportMeetingModal.tsx # 导入弹窗
│   │   │   ├── ProjectSelector.tsx
│   │   │   ├── DocumentList.tsx
│   │   │   └── UploadArea.tsx
│   │   └── hooks/
│   │       └── useProjects.ts
│   └── package.json
│
├── TECH_SPEC.md
└── README.md
```

---

## 7. API 端点

### 会议纪要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/projects/{id}/meetings` | 列出项目下所有会议 |
| POST | `/projects/{id}/meetings` | 创建会议 |
| GET | `/meetings/{id}` | 获取会议详情 |
| PUT | `/meetings/{id}` | 更新会议 |
| DELETE | `/meetings/{id}` | 删除会议（支持所有状态） |
| POST | `/projects/{id}/meetings/import` | 上传文件导入会议（异步队列） |
| GET | `/projects/{id}/meetings/import-status` | 导入状态轮询 |
| POST | `/meetings/{id}/retry-import` | 重试失败的导入 |
| POST | `/meetings/{id}/extract` | 重新提取决议 |

### 决议

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/meetings/{id}/resolutions` | 列出会议决议 |
| POST | `/meetings/{id}/resolutions` | 创建决议 |
| PUT | `/resolutions/{id}` | 更新决议 |
| DELETE | `/resolutions/{id}` | 删除决议 |
| GET | `/resolutions/{id}/chain` | 获取决议关联链 |
| GET | `/projects/{id}/resolutions/active` | 项目下所有活跃决议 |
| POST | `/relations` | 创建关联 |
| DELETE | `/relations` | 删除关联 |

### 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/query` | LLM + RAG 查询 |
| GET/POST | `/config/llm` | LLM 配置管理 |
| GET | `/health` | 健康检查 |
| POST | `/admin/cleanup-resolutions` | 清理重复决议 |

---

## 8. 开发计划

### Phase 1: MVP ✅ 完成

- [x] 项目初始化（uv + Tauri + React）
- [x] 后端基础 API（FastAPI）
- [x] PDF 导入 + PyMuPDF + OCR 解析
- [x] CHM 导入 + 解析
- [x] LanceDB 向量存储
- [x] 混合检索（向量 + 关键词）
- [x] fastembed bge-small-zh embedding（离线）
- [x] 文档元数据管理、去重、断点恢复

### Phase 2: 核心功能 ✅ 完成

- [x] LLM 回答生成（BYOK 模式）
- [x] LLM 配置 API（多厂商支持 + keyring）
- [x] 引用标签生成 + 可点击跳转
- [x] Agent 循环（带工具调用）
- [x] chunk 上下文扩展
- [x] CHM HTML 资源服务
- [x] LlamaIndex Workflow 集成
- [x] keyring 安全存储 API Key

### Phase 3: 会议纪要 ✅ 完成

- [x] Kùzu 图数据库集成
- [x] 会议纪要 CRUD + Timeline 展示
- [x] LLM 自动提取决议 + 关联构建
- [x] 决议关联链（SUPERSEDES/AMENDS/SUPPLEMENTS）
- [x] 孤儿 superseded 恢复
- [x] 异步导入队列 + 状态追踪
- [x] 后端 Router + Service 分层重构
- [x] 前端组件拆分（8 个子组件）
- [x] 59 个 pytest 单元测试
- [x] 代码质量审计 + P0 修复

### Phase 4: 打包发布（待启动）

- [ ] on_event → lifespan handler 迁移
- [ ] 跨平台打包测试（macOS/Windows/Linux）
- [ ] 性能优化
- [ ] 用户文档
- [ ] 开源发布

---

## 9. 依赖清单

### 9.1 后端 (Python)

```toml
[project]
name = "engineer-assistant-backend"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn>=0.27.0",
    "llama-index>=0.10.0",
    "llama-index-workflows>=0.1.0",
    "lancedb>=0.8.0",
    "pymupdf>=1.24.0",
    "rapidocr-onnxruntime>=1.3.0",
    "langchain-text-splitters>=0.3.0",
    "fastembed>=0.2.0",
    "keyring>=24.0.0",
    "httpx>=0.27.0",
    "python-multipart>=0.0.6",
    "kuzu>=0.11.0",
    "pydantic>=2.0.0",
]
```

### 9.2 前端 (Node.js)

```json
{
  "dependencies": {
    "react": "^19.2.4",
    "antd": "^6.3.3",
    "@tauri-apps/api": "^2.10.1",
    "react-markdown": "^10.1.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "typescript": "^5.0.0"
  }
}
```

---

## 10. 风险与备选方案

| 风险 | 影响 | 备选方案 |
|------|------|----------|
| Kùzu 项目归档 | 维护风险 | SQLite + 邻接表 |
| 用户不会配 API Key | 使用门槛 | 详细的引导教程 + Ollama 本地方案 |
| bge-small-zh 效果差 | 检索质量 | 云端 embedding API（可选） |
| Tauri Sidecar 兼容性 | 打包问题 | 纯 PyInstaller |
| LLM 决议提取质量 | 数据准确性 | 人工校验 + 重提