# 项目状态 - 工程设计工作台

## 技术方案
详见 [TECH_SPEC.md](./TECH_SPEC.md)

---

## 当前状态

**阶段：** Phase 1 MVP 进行中

**阻塞：** 无

---

## 已完成

### 环境配置
- [x] 技术栈选型
- [x] 编写技术方案文档 (TECH_SPEC.md)
- [x] 项目目录结构初始化
- [x] 前端依赖安装 (React + Vite + Ant Design + Tauri API)
- [x] Tauri 配置 (Cargo.toml, tauri.conf.json)
- [x] 后端 pyproject.toml 配置
- [x] 系统依赖安装 (gcc, webkit2gtk, etc.)
- [x] Tauri CLI 安装 (2.10.1)
- [x] 后端 Python 依赖安装

### 骨架搭建 (2026-03-18)
- [x] Step 1: 后端最小 API
  - `GET /health` 健康检查
  - `POST /query` 查询接口（mock 回复)
  - ruff 代码风格检查
- [x] Step 2: 前端最小界面
  - 输入框 + 发送按钮 + 回复区域
  - Ant Design 组件
  - ESLint 通过
- [x] Step 3: 前后端连通
  - Python 后端 PyInstaller 打包
  - Tauri sidecar 启动
  - IPC token 传递
  - `cargo tauri dev` 一键启动

### 知识库管理界面 (2026-03-19)
- [x] 知识库视图 (KnowledgeBaseView.tsx)
  - 拖拽上传区域
  - 文档列表展示
  - 删除确认对话框
- [x] Tauri 原生拖拽支持 (Linux/WebKitGTK)
  - 解决 `dragDropEnabled` 与浏览器事件冲突
  - 添加 500ms debounce 防止重复事件
- [x] Tauri 插件集成
  - `tauri-plugin-fs`: 获取文件大小
  - `tauri-plugin-dialog`: 系统文件选择对话框

### 后端文档管理 API (2026-03-19)
- [x] `POST /documents/upload` - 文档上传（本地文件路径）
- [x] `GET /documents` - 文档列表
- [x] `DELETE /documents/{id}` - 文档删除
- [x] SHA256 hash 去重
- [x] JSON 文件存储元数据
- [x] 前后端对接完成

### 开发体验优化 (2026-03-19)
- [x] 修改后端启动逻辑
  - 开发模式：直接运行 uvicorn 源码（无需打包）
  - 生产模式：使用打包的二进制
- [x] 代码风格检查通过 (ruff + ESLint)

### RAG 后端 (2026-03-20)
- [x] PDF 解析模块 (`src/parsers/pdf.py`)
  - RapidOCR 文字识别（支持扫描件）
  - LangChain 文本切分
  - 页码元数据保留
- [x] Embedding 模块 (`src/rag/embeddings.py`)
  - fastembed + bge-small-zh 中文向量模型
  - 模型缓存到本地
- [x] 向量存储模块 (`src/rag/vector_store.py`)
  - LanceDB 存储
  - 语义检索
  - 按文档 ID 删除
- [x] 文档上传集成
  - 后台异步处理（OCR + 切分 + 向量化）
  - 处理状态追踪 (pending/processing/ready/error)
- [x] 查询接口升级
  - `POST /query` 返回相关片段
  - 引用标签（文档 ID + 页码）
  - 上下文拼接

### 前端 RAG 集成 (2026-03-21)
- [x] 知识库界面 - 处理进度实时显示
- [x] 聊天界面 - 引用标签展示
- [x] 处理日志带时间戳
- [x] 中断处理 + 恢复机制
- [x] 混合检索（向量 + 关键词）
- [x] OCR 并行处理优化 - **5.5 倍提速**

### CHM 文档支持 (2026-03-22)
- [x] CHM 解析模块 (`src/parsers/chm.py`)
  - 7z 解压到临时目录
  - BeautifulSoup 提取 HTML 文本
  - location 字段（文件路径）代替页码
- [x] 向量存储支持 location 字段
- [x] 文档上传支持 CHM 格式
- [x] 查询结果显示 location（CHM 用路径，PDF 用页码）

### 前端 CHM 支持 (2026-03-24)
- [x] KnowledgeBaseView - 支持 CHM 上传
  - 文件选择/拖拽支持 .chm 格式
  - 文档列表显示文件类型标签（PDF/CHM）
  - 不同文件类型使用不同图标
- [x] ChatView - 支持 location 字段显示
  - Citation 接口添加 location 字段
  - 引用标签智能显示：CHM 用路径，PDF 用页码
- [x] 后端 Citation 模型添加 location 字段

### Bug 修复与数据迁移 (2026-03-24)
- [x] CHM 编码问题修复
  - 添加编码自动检测（优先 HTML meta charset）
  - 默认使用 gb18030（GBK 超集）
- [x] 数据迁移机制
  - Schema 版本控制（CURRENT_SCHEMA_VERSION = 2）
  - 启动时版本检查与警告
  - `POST /documents/{id}/reprocess` API - 单文档重新处理
  - `POST /documents/reprocess-all` API - 批量重新处理
  - 前端"重建索引"按钮
- [x] 离线模式优化
  - 强制启用 HF_HUB_OFFLINE（国内网络环境）
  - 消除 HuggingFace 连接警告

### LLM 生成回答 (2026-03-27)
- [x] LLM 客户端 (`src/llm/client.py`)
  - OpenAI 兼容 API 调用（httpx async）
  - 模块级连接池复用
  - API 错误信息透传
- [x] Agent 循环 (`src/llm/agent.py`)
  - 带 function calling 的多轮工具调用
  - 防御性 response 访问
  - 自动引用提取 `[来源:xxx]`
- [x] 知识库搜索工具 (`src/llm/tools.py`)
  - search_knowledge_base 工具定义
  - 异常脱敏，不暴露内部细节
- [x] System Prompt (`src/llm/prompts.py`)
  - 强制工具调用、禁止编造、引用格式规范
- [x] LLM 配置管理 (`src/utils/llm_config.py`)
  - 多 provider 支持（智谱/DeepSeek/通义/Ollama/自定义）
  - keyring 存储 API Key
  - 内存缓存 config.json（读写分离）
- [x] 配置 API (`src/routers/config.py`)
  - GET/POST/DELETE /config/llm
  - 启动时自动从 .env 初始化
  - model 空值校验
- [x] CHM 解析容错 (2026-03-27)
  - BeautifulSoup 失败时正则 fallback
  - 解决 `&#402;` 等 HTML 实体解析错误
- [x] Embedding 离线优化 (2026-03-27)
  - `local_files_only=True`，彻底消除 HuggingFace 连接尝试
- [x] 知识库更新 (2026-03-27)
  - 导入《结构专业规范大全2023年10月版》(540MB CHM)
  - 删除旧版 22本强制性规范 CHM
  - 总计 22860 chunks（含《建筑设计防火规范》GB 50016 等）

### LlamaIndex Workflow 集成 (2026-04-08)
- [x] `src/llm/workflow.py` — QueryWorkflow 三步式架构
  - ToolCallStep: LLM + 工具执行循环（最多 3 轮）
  - ExpandContextStep: 相邻 chunk 上下文扩展
  - GenerateStep: 注入扩展上下文，生成带引用的回答
- [x] `src/llm/agent.py` — 精简为薄封装，委托给 Workflow
- [x] 状态通过类型化 Event 传递（ExpandContextEvent / GenerateEvent）
- [x] 辅助函数拆分：`_expand_single_doc`、`_deduplicate_chunks`、`_format_source_label`
- [x] 代码质量：英文 docstring、lazy logging、绝对导入、ruff 全通过
- [x] 功能测试通过：回答正确、引用溯源正常

## 下一步

- [ ] 会议纪要图谱查询（Kùzu 图数据库）
- [ ] 前端优化（回答展示、引用高亮）

---

## 性能数据

**35MB PDF（72 页全需 OCR）处理时间：**
- 优化前：~20 分钟
- 优化后：3.6 分钟（215s）
- **提升约 5.5 倍**

**30MB CHM（22本强制性规范）处理时间：**
- 解析：0.67s（944 HTML → 1215 分块）
- 向量化：22.65s

**优化措施：**
- 原生 PDF 直接提取文字，跳过 OCR
- ThreadPoolExecutor 并行处理 OCR 页面
- 每个线程独立的 OCR 引擎

---

## 备注

- 启动命令: `cargo tauri dev`
- 宿舍断电：工作日 0:00-6:00
- 后端数据目录: `backend/data/`
  - `uploads/`: 上传的 PDF/CHM 文件
  - `vectors/`: LanceDB 向量存储 + embedding 缓存
  - `documents.json`: 文档元数据
