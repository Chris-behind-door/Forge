# 工程设计工作台 - 技术方案文档

> 版本: 2.0
> 日期: 2026-03-27
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
2. **会议纪要 RAG** - 检索 + 关联关系追踪（"否定之否定"）
3. **分流智能体** - 自动判断查询对象
4. **BYOK** - 用户自带 API Key，支持多个 LLM 厂商

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

**备选方案:** Nuitka（不支持 Python 3.14，排除）

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

**Workflow 架构:**

```
StartEvent
    ↓
QueryRouted (分流智能体)
    ├── 技术资料 → RetrieveTechDocs → GenerateWithCitation
    └── 会议纪要 → RetrieveMeetingNotes → TraceRelations → GenerateWithCitation
```

### 2.7 向量库: LanceDB

**选型理由**
- 嵌入式，无需服务器
- 多模态支持（向量 + 全文 + SQL + 混合搜索）
- 性能好（列式存储）
- LlamaIndex 原生集成

**备选方案:** Chroma（功能较少）

### 2.8 图数据库: Kùzu

**选型理由**
- **MIT 许可证**（Neo4j 是 GPL，商业分发受限）
- 原生嵌入式设计
- 支持 Cypher 查询语言
- 内置向量索引
- 体积小（~20MB vs Neo4j ~100MB+）

**注意:** Kùzu 项目已归档，但 0.11.3 版本稳定可用

### 2.9 文档解析: PyMuPDF + RapidOCR（当前方案）

**已实现：**
- PyMuPDF 直接提取 PDF 文字
- RapidOCR (ONNX Runtime) 处理扫描件
- 线程池并行 OCR
- CHM 解析（7z 解压 + HTML 文本提取）

**备选（未实现）：** Docling（高级 PDF 能力：表格、公式、代码、图表、多格式 DOCX/PPTX/HTML/OCR）

### 2.10 Embedding 模型: fastembed + bge-small-zh ✅ 已实现

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
│  │  ├── 资料导入                                    │   │   │
│  │  ├── 查询界面                                    │   │   │
│  │  ├── 设置（API Key 配置）                        │   │   │
│  │  └── 结果展示（含引用标签）                       │   │   │
│  └─────────────────────────────────────────────────│───┘   │
│                                                    │       │
│  ┌─────────────────────────────────────────────────│───┐   │
│  │  后端 (FastAPI + PyInstaller)  ◄────────────────┘   │   │
│  │  ├── API 服务                                       │   │
│  │  │   ├── POST /query          # 查询（LLM + RAG）   │   │
│  │  │   ├── POST /documents      # 导入文档            │   │
│  │  │   ├── GET  /documents      # 文档列表            │   │
│  │  │   ├── GET  /documents/{id} # 单文档信息          │   │
│  │  │   ├── GET  /documents/{id}/chunks/{idx} # Chunk详情│   │
│  │  │   ├── GET  /documents/{id}/file   # 文件预览     │   │
│  │  │   ├── GET  /documents/{id}/chm-html # CHM HTML   │   │
│  │  │   ├── GET  /config/llm     # LLM 配置            │   │
│  │  │   ├── POST /config/llm     # 设置 LLM 配置       │   │
│  │  │   ├── GET  /health         # 健康检查            │   │
│  │  │   └── ...                                        │   │
│  │  │                                                  │   │
│  │  ├── LlamaIndex Workflow                            │   │
│  │  │   ├── 分流智能体                                  │   │
│  │  │   ├── RAG 检索                                    │   │
│  │  │   └── 引用溯源                                    │   │
│  │  │                                                  │   │
│  │  ├── LanceDB (向量存储)                             │   │
│  │  ├── Kùzu (图数据库)                                │   │
│  │  └── 文档解析 (PDF/CHM)                             │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  数据存储                                            │   │
│  │  ~/.engineer_assistant/                             │   │
│  │  ├── data/                  # 资料库                 │   │
│  │  │   ├── uploads/           # 上传的文档             │   │
│  │  │   ├── vectors/           # LanceDB 向量数据       │   │
│  │  │   ├── kuzu/              # 图数据                 │   │
│  │  │   └── documents.json     # 文档元数据            │   │
│  │  ├── models/               # 本地模型                │   │
│  │  │   └── fastembed/         # embedding 模型缓存     │   │
│  │  └── config.json           # 用户配置               │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘

外部依赖（仅 LLM API，用户自配）:
┌─────────────────────┐
│  用户自配 LLM API    │
│                     │
│  - 智谱 GLM         │
│  - DeepSeek         │
│  - 阿里通义          │
│  - Ollama (本地)    │
│  - 其他兼容 API     │
│                     │
│  Key 存储在系统密钥链 │
└─────────────────────┘
```

---

## 4. 核心模块设计

### 4.1 LLM 配置管理 (BYOK)

**设计原则：**
- 用户自行配置 API Key，应用不提供任何内置 Key
- Key 存储在系统密钥链（keyring），不明文保存
- 支持多个 LLM 厂商，用户可随时切换
- 未配置 Key 时，仅支持本地检索（离线模式）

**支持的厂商：**

| 厂商 | API Base | 备注 |
|------|----------|------|
| 智谱 GLM | https://open.bigmodel.cn/api/paas/v4 | 默认推荐 |
| DeepSeek | https://api.deepseek.com/v1 | 性价比高 |
| 阿里通义 | https://dashscope.aliyuncs.com/compatible-mode/v1 | |
| Ollama | http://localhost:11434/v1 | 本地部署，完全离线 |
| 自定义 | 用户填写 | 任意 OpenAI 兼容 API |

**配置 API：**

```python
# GET /config/llm - 获取当前 LLM 配置
# 返回已配置的厂商列表（不返回 Key 明文，只返回是否已配置）
{
    "providers": [
        {"id": "zhipu", "name": "智谱 GLM", "configured": true},
        {"id": "deepseek", "name": "DeepSeek", "configured": false},
        {"id": "ollama", "name": "Ollama (本地)", "configured": false}
    ],
    "active_provider": "zhipu",
    "model": "glm-4-flash"
}

# POST /config/llm - 设置 LLM 配置
{
    "provider": "zhipu",        # 厂商 ID
    "api_key": "sk-xxx",        # API Key（存入 keyring）
    "model": "glm-4-flash",     # 模型名
    "base_url": null            # 可选，自定义 API Base
}
```

**Key 存储（keyring）：**

```python
import keyring

SERVICE_NAME = "engineer_assistant"

def save_api_key(provider: str, api_key: str):
    keyring.set_password(SERVICE_NAME, f"{provider}_api_key", api_key)

def get_api_key(provider: str) -> str | None:
    return keyring.get_password(SERVICE_NAME, f"{provider}_api_key")

def delete_api_key(provider: str):
    keyring.delete_password(SERVICE_NAME, f"{provider}_api_key")
```

**离线模式：**
- 未配置 LLM Key 时，仅支持本地向量检索
- 返回检索到的原始文档片段（当前已实现的行为）
- 前端提示用户配置 Key 以获得 AI 回答

### 4.2 分流智能体 (Router Agent)

**职责:** 判断用户查询应该走技术资料库还是会议纪要库

```python
from llama_index.core.workflow import Workflow, step, StartEvent, StopEvent, Event

class QueryRouted(Event):
    target: str  # "tech_docs" | "meeting_notes"
    query: str

class RouterWorkflow(Workflow):
    @step
    async def route_query(self, ev: StartEvent) -> QueryRouted:
        query = ev.query
        
        # 简单规则判断（后续可用 LLM 增强）
        meeting_keywords = ["决议", "会议", "确定", "决定", "之前说的"]
        if any(kw in query for kw in meeting_keywords):
            return QueryRouted(target="meeting_notes", query=query)
        else:
            return QueryRouted(target="tech_docs", query=query)
```

### 4.3 RAG 检索 (Retriever) ✅ 已实现基础版

**已实现：**
- fastembed bge-small-zh embedding（离线）
- LanceDB 向量存储
- 混合检索（向量语义 + 关键词匹配）
- PDF 解析（直接提取 + OCR fallback + 并行）
- CHM 解析（7z + HTML 文本提取）
- 文档元数据管理、去重、断点恢复

**待实现（LlamaIndex 升级）：**
- 父子切片策略（HierarchicalNodeParser）
- 检索时用子节点匹配，返回父节点上下文

### 4.4 LLM 回答生成 (待实现)

**引用溯源 prompt：**

```python
CITATION_PROMPT = """
你是一个专业的工程设计助手。回答问题时必须：

1. 每个事实陈述都要标注来源，格式：[来源:文档名#页码]
2. 区分"事实"和"推断"
3. 如果信息来自会议纪要，标注会议日期

示例回复：
---
根据 [来源:技术规范v2.1#P15]，混凝土强度等级不应低于C30。

结合 [来源:2024-03会议纪要#决议3] 中确定的设计变更要求，
我推断（⚠️推断）需要调整配筋方案。
---
"""
```

### 4.5 会议纪要关联 (Graph Engine) (待实现)

**Kùzu 图查询：**

```python
import kuzu

db = kuzu.Database("~/.engineer_assistant/data/kuzu")
conn = kuzu.Connection(db)

# 创建表
conn.execute("""
    CREATE NODE TABLE MeetingNote (
        id STRING,
        content STRING,
        date DATE,
        topic STRING,
        PRIMARY KEY (id)
    )
""")

conn.execute("""
    CREATE REL TABLE SUPERSEDES (FROM MeetingNote TO MeetingNote)
""")

# 查询某个决议的完整链路
def trace_resolution(note_id: str) -> list:
    result = conn.execute("""
        MATCH path = (n:MeetingNote)-[:SUPERSEDES|AMENDS|SUPPLEMENTS*]->(m:MeetingNote)
        WHERE m.id = $note_id
        RETURN path
        ORDER BY n.date
    """, {"note_id": note_id})
    
    return result.get_as_df()
```

---

## 5. 端口与进程管理

### 5.1 端口动态分配

Tauri 启动 Sidecar 时动态分配端口，通过约定文件传递：

```python
import socket

def find_available_port(start: int = 8765, max_tries: int = 100) -> int:
    for port in range(start, start + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(('', port))
                return port
        except OSError:
            continue
    raise RuntimeError("No available port found")

# 启动时写入端口文件
PORT_FILE = Path.home() / ".engineer_assistant" / ".port"
```

### 5.2 前后端通信

前端通过 Tauri event 获取后端端口，或读取端口文件。无 IPC 鉴权（本地应用，无安全风险）。

---

## 6. 部署与打包

### 6.1 目录结构

```
engineer_assistant/
├── backend/                    # 客户端后端
│   ├── src/
│   │   ├── main.py            # FastAPI 入口
│   │   ├── routers/
│   │   │   ├── documents.py   # ✅ 文档管理
│   │   │   ├── query.py       # 查询（待实现 LLM 生成）
│   │   │   └── config.py      # LLM 配置（待实现）
│   │   ├── rag/
│   │   │   ├── embeddings.py  # ✅ fastembed
│   │   │   ├── vector_store.py # ✅ LanceDB
│   │   │   ├── workflow.py    # LlamaIndex Workflow（待实现）
│   │   │   ├── retriever.py   # 待实现
│   │   │   └── citation.py    # 待实现
│   │   ├── parsers/
│   │   │   ├── pdf.py         # ✅ PyMuPDF + OCR
│   │   │   └── chm.py         # ✅
│   │   └── utils/
│   │       ├── paths.py       # ✅
│   │       ├── port.py        # 端口分配（待实现）
│   │       └── keyring.py     # API Key 存储（待实现）
│   ├── pyproject.toml
│   └── build.spec             # PyInstaller 配置
│
├── frontend/                   # 客户端前端
│   ├── src/
│   │   ├── App.tsx
│   │   └── views/
│   ├── package.json
│   └── dist/                   # 打包后
│
├── src-tauri/                  # Tauri 配置
│   ├── src/
│   │   └── main.rs
│   ├── tauri.conf.json
│   └── binaries/               # Sidecar 放这里
│       └── backend-{target}/
│
├── TECH_SPEC.md               # 本文档
└── README.md
```

### 6.2 打包流程

```bash
# 1. 打包后端
cd backend
uv run pyinstaller build.spec
# 输出: dist/backend (可执行文件)

# 2. 打包前端
cd frontend
npm run build
# 输出: dist/ (静态文件)

# 3. 复制 Sidecar
cp backend/dist/backend src-tauri/binaries/backend-x86_64-unknown-linux-gnu

# 4. 打包 Tauri
cargo tauri build
# 输出:
#   - src-tauri/target/release/bundle/appimage/ (Linux)
#   - src-tauri/target/release/bundle/dmg/ (macOS)
#   - src-tauri/target/release/bundle/msi/ (Windows)
```

### 6.3 体积预估

| 组件 | 体积 |
|------|------|
| Tauri 框架 | ~3MB |
| Python Sidecar | ~80MB |
| 前端 | ~5MB |
| fastembed 模型（首次下载） | ~100MB |
| **总计（安装包）** | **~90MB** |
| **总计（含模型）** | **~190MB** |

---

## 7. 开发计划

### Phase 1: MVP ✅ 基础完成

- [x] 项目初始化（uv + Tauri + React）
- [x] 后端基础 API（FastAPI）
- [x] PDF 导入 + PyMuPDF + OCR 解析
- [x] CHM 导入 + 解析
- [x] LanceDB 向量存储
- [x] 混合检索（向量 + 关键词）
- [x] fastembed bge-small-zh embedding（离线）
- [x] 文档元数据管理、去重、断点恢复

### Phase 2: 核心功能（进行中）

- [x] LLM 回答生成（BYOK 模式）
- [x] LLM 配置 API（多厂商支持，暂用 localStorage）
- [x] 引用标签生成（[来源:文档名#位置] 格式）
- [x] Agent 循环（带工具调用，最多 3 次查询 + 2 轮强制回答）
- [x] 前端查询界面（markdown 渲染 + [引用:xxx] 内联标签）
- [x] 前端设置页面（API Key 配置 + 自定义配置管理）
- [x] 检索结果文档名显示（而非 UUID）
- [x] chunk 上下文扩展（检索到片段后前后各 1 个 chunk）
- [x] 引用标签可点击跳转（PDF 打开到指定页码，CHM 浏览器查看 HTML）
- [x] CHM HTML 资源服务（图片/CSS/JS + 编码检测 + URL 重写）
- [x] 纯 BYOK 模式确认，废弃 proxy 中转服务器
- [x] LlamaIndex Workflow 集成（QueryWorkflow: ToolCallStep → ExpandContextStep → GenerateStep）
- [x] ~~分流智能体~~ → 由主 Agent 自行判断查哪边，不单独分（已取消）
- [x] keyring 安全存储 API Key

### Phase 3: 进阶功能（计划: 下周末启动图数据库）

- [ ] 图数据库集成（Kùzu 或 SQLite+邻接表，待评估）
- [ ] 会议纪要关联查询
- [ ] Docling 高级文档解析（表格、公式、DOCX/PPTX/HTML 多格式）
- [ ] 端口动态分配 ← 当前任务
- [ ] 性能优化

### Phase 4: 发布与文档

- [ ] 跨平台打包测试（macOS/Windows/Linux）
- [ ] GitHub Actions CI（Windows 已跑通）
- [ ] 用户文档
- [ ] 开源发布

---

## 8. 依赖清单

### 8.1 后端 (Python)

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
    "kuzu>=0.3.0",
    "pymupdf>=1.24.0",
    "rapidocr-onnxruntime>=1.3.0",
    "langchain-text-splitters>=0.3.0",
    "fastembed>=0.2.0",
    "keyring>=24.0.0",
    "httpx>=0.27.0",
    "python-multipart>=0.0.6",
    "pyinstaller>=6.19.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

### 8.2 前端 (Node.js)

```json
{
  "dependencies": {
    "react": "^18.2.0",
    "antd": "^5.12.0",
    "@tauri-apps/api": "^2.0.0",
    "@tauri-apps/plugin-shell": "^2.0.0"
  },
  "devDependencies": {
    "vite": "^5.0.0",
    "typescript": "^5.0.0"
  }
}
```

---

## 9. 风险与备选方案

| 风险 | 影响 | 备选方案 |
|------|------|----------|
| Kùzu 项目归档 | 维护风险 | SQLite + 邻接表 |
| 用户不会配 API Key | 使用门槛 | 详细的引导教程 + Ollama 本地方案 |
| bge-small-zh 效果差 | 检索质量 | 云端 embedding API（可选） |
| Tauri Sidecar 兼容性 | 打包问题 | 纯 PyInstaller |

---

## 10. 参考

- [LlamaIndex Workflow 文档](https://docs.llamaindex.ai/en/stable/understanding/workflows/)
- [LanceDB 文档](https://docs.lancedb.com/)
- [Kùzu 文档](https://kuzudb.github.io/docs/)
- [Tauri 2.0 文档](https://v2.tauri.app/)
- [uv 文档](https://docs.astral.sh/uv/)
