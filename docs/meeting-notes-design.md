# 会议纪要功能 — 设计文档

> 版本: 1.0 | 日期: 2026-04-20 | 状态: 草案

---

## 1. 数据模型

### 1.1 设计思路

- **项目分组**通过 `Project` 节点实现，所有会议和决议挂在其下
- Kùzu 存储图结构（关联关系），JSON 文件存储会议/决议的完整内容（与现有 `documents.json` 模式一致）
- 决议（Resolution）是核心节点，关联关系是核心边

### 1.2 Kùzu Node Tables

```cypher
-- 项目
CREATE NODE TABLE Project (
    id STRING,
    name STRING,
    description STRING,
    created_at STRING,
    PRIMARY KEY (id)
)

-- 会议
CREATE NODE TABLE Meeting (
    id STRING,
    project_id STRING,
    title STRING,
    date STRING,         -- ISO 8601
    summary STRING,      -- 会议摘要（LLM 生成）
    source_doc_id STRING, -- 关联的已上传文档 ID（可选）
    raw_text STRING,     -- 原始纪要文本
    created_at STRING,
    PRIMARY KEY (id)
)

-- 决议
CREATE NODE TABLE Resolution (
    id STRING,
    meeting_id STRING,
    project_id STRING,
    content STRING,       -- 决议内容
    index INT,            -- 在会议中的序号（决议1、决议2...）
    status STRING DEFAULT 'active',  -- active / superseded / amended
    source_doc_id STRING, -- 来源文档 chunk（可选，用于溯源）
    created_at STRING,
    PRIMARY KEY (id)
)
```

### 1.3 Kùzu Rel Tables

```cypher
-- 关联类型：取代（完全替换旧决议）
CREATE REL TABLE SUPERSEDES (FROM Resolution TO Resolution,
    meeting_id STRING,    -- 在哪个会议中做出的取代决定
    reason STRING         -- LLM 提取的原因
)

-- 关联类型：修改（部分修改旧决议）
CREATE REL TABLE AMENDS (FROM Resolution TO Resolution,
    meeting_id STRING,
    change_summary STRING  -- 修改了什么
)

-- 关联类型：补充（补充说明旧决议）
CREATE REL TABLE SUPPLEMENTS (FROM Resolution TO Resolution,
    meeting_id STRING,
    supplement_content STRING
)

-- 隶属关系
CREATE REL TABLE CONTAINS_MEETING (FROM Project TO Meeting)
CREATE REL TABLE CONTAINS_RESOLUTION (FROM Meeting TO Resolution)
```

### 1.4 辅助存储

沿用 JSON 文件模式（与现有 `documents.json` 风格一致）：

- `data/meetings.json` — 会议元数据列表（含项目 ID、标题、日期、状态）
- `data/resolutions.json` — 决议元数据列表（含会议 ID、内容、索引）
- `data/kuzu/` — Kùzu 数据库文件（图结构 + 关联关系）

**为什么不全放 Kùzu？** JSON 文件方便批量读写和列表查询，Kùzu 擅长关联查询。职责分离。

---

## 2. API 设计

### 2.1 项目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/projects` | 列出所有项目 |
| `POST` | `/projects` | 创建项目 |
| `GET` | `/projects/{id}` | 项目详情（含会议列表） |
| `PUT` | `/projects/{id}` | 更新项目信息 |
| `DELETE` | `/projects/{id}` | 删除项目（级联删除会议和决议） |

**请求/响应示例：**

```json
// POST /projects
{ "name": "XX大桥设计", "description": "XX大桥施工图设计项目" }

// GET /projects/{id}
{
  "id": "proj_abc",
  "name": "XX大桥设计",
  "description": "...",
  "meeting_count": 5,
  "resolution_count": 23,
  "meetings": [
    {"id": "mtg_1", "title": "第3次设计审查会", "date": "2026-04-15", "resolution_count": 6}
  ]
}
```

### 2.2 会议管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/projects/{pid}/meetings` | 项目下的会议列表 |
| `POST` | `/projects/{pid}/meetings` | 创建会议（可关联已有文档） |
| `GET` | `/meetings/{id}` | 会议详情（含决议列表） |
| `PUT` | `/meetings/{id}` | 更新会议信息 |
| `DELETE` | `/meetings/{id}` | 删除会议 |

```json
// POST /projects/{pid}/meetings
{
  "title": "第4次设计审查会",
  "date": "2026-04-20",
  "raw_text": "会议内容全文...",
  "source_doc_id": null  // 可选，关联已上传文档
}
```

### 2.3 决议 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/meetings/{mid}/resolutions` | 会议的决议列表 |
| `POST` | `/meetings/{mid}/resolutions` | 手动创建决议 |
| `PUT` | `/resolutions/{id}` | 修改决议内容 |
| `DELETE` | `/resolutions/{id}` | 删除决议（同时删除关联边） |

### 2.4 关联查询

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/resolutions/{id}/chain` | 查询决议的完整变更链路 |
| `GET` | `/projects/{pid}/resolutions/active` | 项目的所有有效决议（status=active） |
| `GET` | `/projects/{pid}/graph` | 项目的决议关联图（用于可视化） |

**`/resolutions/{id}/chain` 响应：**

```json
{
  "target": {"id": "res_5", "content": "采用C40混凝土", "meeting": "第4次审查会"},
  "chain": [
    {
      "resolution": {"id": "res_1", "content": "采用C30混凝土", "meeting": "第1次审查会"},
      "relation": "SUPERSEDES",
      "reason": "根据地质报告，需提高强度等级"
    },
    {
      "resolution": {"id": "res_5", "content": "采用C40混凝土", "meeting": "第4次审查会"},
      "relation": null,
      "reason": null
    }
  ]
}
```

**`/projects/{pid}/graph` 响应：**

```json
{
  "nodes": [
    {"id": "res_1", "content": "...", "meeting_id": "mtg_1", "status": "superseded"},
    {"id": "res_5", "content": "...", "meeting_id": "mtg_4", "status": "active"}
  ],
  "edges": [
    {"from": "res_5", "to": "res_1", "type": "SUPERSEDES", "reason": "..."}
  ]
}
```

### 2.5 关联修正

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/resolutions/relations` | 手动创建关联 |
| `PUT` | `/resolutions/relations/{id}` | 修改关联类型/原因 |
| `DELETE` | `/resolutions/relations/{id}` | 删除关联 |

```json
// POST /resolutions/relations
{
  "from_id": "res_5",
  "to_id": "res_1",
  "relation_type": "SUPERSEDES",  // SUPERSEDES | AMENDS | SUPPLEMENTS
  "reason": "手动标注"
}
```

### 2.6 LLM 提取

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/meetings/{id}/extract` | 对已有会议纪要执行 LLM 提取 |
| `POST` | `/meetings/extract-preview` | 预览提取结果（不保存） |

创建会议时如果提供了 `raw_text`，自动触发提取流程。也可手动触发重新提取。

---

## 3. LLM 提取流程

### 3.1 整体流程

```
用户上传会议纪要文本
        ↓
  Step 1: 提取决议
  (结构化 JSON 输出)
        ↓
  Step 2: 匹配历史决议
  (与项目内已有决议比对)
        ↓
  Step 3: 建立关联
  (写入 Kùzu)
        ↓
  Step 4: 展示给用户确认
  (可修正)
```

### 3.2 Step 1: 提取决议

一次 LLM 调用，使用结构化输出：

```python
EXTRACT_PROMPT = """从以下会议纪要中提取所有决议。

输出 JSON 格式：
{
  "resolutions": [
    {
      "index": 1,
      "content": "决议内容（简洁准确）",
      "context": "该决议的上下文（谁提出的、讨论要点）"
    }
  ]
}

要求：
- 每个独立的决定/共识提取为一条决议
- 保留关键数据（数值、标准、人名）
- 忽略纯讨论过程，只提取最终决定

会议纪要：
---
{raw_text}
---"""
```

### 3.3 Step 2: 匹配历史决议

拿到新决议后，逐条与项目内已有决议比对：

```python
MATCH_PROMPT = """判断新决议与已有决议的关系。

新决议：{new_resolution}

已有决议列表：
{existing_resolutions}

输出 JSON：
{
  "relations": [
    {
      "new_index": 1,
      "existing_id": "res_3",
      "type": "SUPERSEDES",  // SUPERSEDES | AMENDS | SUPPLEMENTS | NONE
      "reason": "原因"
    }
  ]
}

判断标准：
- SUPERSEDES：新决议完全替代旧决议（如"改为XX"、"不用XX了"）
- AMENDS：新决议修改旧决议的部分内容（如"在原方案基础上增加XX"）
- SUPPLEMENTS：新决议补充说明旧决议（如"上次那个决议，补充说明如下"）
- NONE：无直接关联"""
```

**优化策略：** 先用 embedding 相似度筛选 top-K 候选（复用 bge-small-zh），再送 LLM 判断。避免把全部历史决议塞进 prompt。

### 3.4 Step 3: 写入 Kùzu

```python
# 写入决议节点
for r in resolutions:
    conn.execute("CREATE (r:Resolution {id: $id, ...})", {...})

# 写入关联边
for rel in relations:
    if rel.type != "NONE":
        conn.execute(
            "MATCH (a:Resolution),(b:Resolution) "
            "WHERE a.id=$from AND b.id=$to "
            "CREATE (a)-[:{rel.type} {meeting_id: $mid}]->(b)",
            {...}
        )
        # 更新被关联决议的状态
        if rel.type == "SUPERSEDES":
            update_status(rel.existing_id, "superseded")
        elif rel.type == "AMENDS":
            update_status(rel.existing_id, "amended")
```

### 3.5 错误容忍

- 提取失败不阻塞保存，用户可手动添加决议
- 匹配置信度低的关系标记为 `needs_review`，前端高亮提示
- 用户确认后才更新决议状态

---

## 4. 跨文档关联策略

### 4.1 挑战

会议纪要中的引用往往是模糊的：
- "上次那个决议我们改了"
- "之前确定的方案调整如下"
- "第三次审查会的决议3需要修改"

### 4.2 策略：LLM + embedding 两阶段匹配

**阶段一：Embedding 预筛选**

对每条新决议，用 bge-small-zh 计算与项目内所有已有决议的相似度，取 top-10 候选。

**阶段二：LLM 语义匹配**

将候选决议（含上下文：会议标题、日期、决议序号）交给 LLM 判断具体关联。

**关键：提供上下文信息。** LLM 看到的不是孤立的决议文本，而是：

```
已有决议（来自本项目）：
1. [2026-03-10 第1次审查会 决议3] 采用C30混凝土
2. [2026-03-25 第2次审查会 决议1] 桥墩基础采用桩基方案
3. [2026-04-05 第3次审查会 决议2] 根据地勘报告，调整桩长至25m
...
```

这样 LLM 能理解"上次那个关于桩基的决议"指的是哪条。

### 4.3 显式引用提取

在提取决议时，额外让 LLM 提取**引用信号**：

```python
# 在 EXTRACT_PROMPT 中增加：
"references": [
  {
    "resolution_index": 1,
    "refers_to": "之前关于混凝土等级的决议",
    "confidence": "high"  // high / medium / low
  }
]
```

这些引用信号帮助缩小匹配范围。高置信引用直接匹配，低置信走 embedding + LLM 二次确认。

### 4.4 同一项目内限定

所有关联匹配仅在**同一项目**内进行。不同项目的决议之间不产生关联，避免误匹配。

---

## 5. 前端交互方案

### 5.1 项目管理页

- 左侧项目列表（antd `Menu` 或 `List`），点击切换
- 右侧显示项目下的会议时间线（antd `Timeline`）
- 新建/编辑项目的 Modal

### 5.2 会议详情页

- 顶部：会议元信息（标题、日期、关联文档）
- 中部：决议卡片列表（antd `Card`），每张卡片显示：
  - 决议内容
  - 状态标签（`Tag`）：🟢 active / 🟡 amended / 🔴 superseded
  - 关联指示器（如果有关联，显示箭头图标）
- 底部：原始纪要文本（可折叠）

### 5.3 决议关联图（核心交互）

**方案：用 antd `Tree` 或简单的自定义 SVG/Canvas 画连线。**

不建议引入重型图可视化库（如 G6），用轻量方案：

- **时间线视图**（推荐首选）：水平时间线，决议按会议分组排列，关联用连线表示
- 交互：
  - 点击决议节点 → 展开详情面板
  - 点击连线 → 显示关联类型和原因
  - 拖拽连线 → 修改关联（或右键菜单）

**更务素的方案：表格 + 弹窗。**

考虑到 antd 生态和实现成本，推荐先用表格方案：

- 决议列表表格，每行有"关联"按钮
- 点击弹出 Modal，显示该决议的完整变更链路（`Steps` 组件，从最早到最新）
- Modal 内可添加/删除/修改关联关系

### 5.4 手动修正关联

**操作流程：**

1. 在决议详情中点击"编辑关联"
2. 弹出 Modal：
   - 当前决议信息
   - 已有关联列表（可删除）
   - "添加关联"按钮 → 选择目标决议（项目内搜索）+ 选择关联类型 + 填写原因
3. 保存后立即更新图数据

**决议搜索：** 使用 antd `Select` + `debounce` 搜索，后端 `/projects/{id}/resolutions/active` 提供数据。

### 5.5 LLM 提取结果确认

创建会议后，如果 LLM 提取了决议和关联：

1. 显示"提取结果"面板，列出所有决议和检测到的关联
2. 关联标记置信度（🟢高 / 🟡中 / 🔴低）
3. 用户可以：
   - ✅ 确认单条
   - ❌ 删除错误项
   - ✏️ 编辑内容
   - 批量确认
4. 确认后写入 Kùzu

---

## 6. 后端模块结构

```
backend/src/
├── routers/
│   ├── meetings.py          # 新增：会议 + 决议 + 关联 API
│   └── projects.py          # 新增：项目 API
├── graph/
│   ├── __init__.py
│   ├── db.py                # Kùzu 连接管理 + schema 初始化
│   ├── queries.py           # Cypher 查询封装
│   └── extract.py           # LLM 提取逻辑
├── models/
│   ├── meeting.py           # 新增：Meeting/Resolution Pydantic 模型
│   └── project.py           # 新增：Project Pydantic 模型
```

### Kùzu 连接管理

```python
# graph/db.py
import kuzu
from pathlib import Path

KUZU_DIR = Path("~/.engineer_assistant/data/kuzu").expanduser()
_db: kuzu.Database | None = None

def get_db() -> kuzu.Database:
    global _db
    if _db is None:
        KUZU_DIR.mkdir(parents=True, exist_ok=True)
        _db = kuzu.Database(str(KUZU_DIR))
        _init_schema(_db)
    return _db

def get_conn() -> kuzu.Connection:
    return kuzu.Connection(get_db())

def _init_schema(db):
    """创建表（IF NOT EXISTS 语义用 try/except 模拟）"""
    conn = kuzu.Connection(db)
    # 按顺序创建，依赖关系决定顺序
    for ddl in SCHEMAS:
        try:
            conn.execute(ddl)
        except Exception:
            pass  # 表已存在
```

---

## 7. 实现优先级

### P0（最小可用）
1. 项目 CRUD + 会议 CRUD（JSON 存储）
2. 手动创建决议
3. Kùzu schema + 手动关联
4. 关联链路查询

### P1（核心价值）
5. LLM 自动提取决议
6. LLM 跨会议关联匹配
7. 前端关联可视化

### P2（锦上添花）
8. 与已有文档关联（上传会议纪要 PDF → 自动提取）
9. 决议全文搜索（embedding 向量检索）
10. 导出报告

---

## 8. 开放问题

1. **Kùzu 并发**：Kùzu 单进程写入，多请求需要加锁。用 `asyncio.Lock` 即可。
2. **版本冲突**：如果两个用户同时修改关联关系？→ 桌面单用户应用，暂不处理。
3. **大历史项目**：决议数量 >1000 时 embedding 预筛选的性能？→ 先做，有问题再优化。
4. **Kùzu 归档风险**：项目已归档不再更新，但有 bug 不会修。→ 锁定 0.11.3，必要时可换 SQLite + 邻接表模拟图查询。
