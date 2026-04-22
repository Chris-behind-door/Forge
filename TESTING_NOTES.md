# 前端测试笔记 (agent-browser)

## 启动

```bash
# 前端
cd ~/programming/engineer_assistant/frontend && npm run dev
# 后端
nohup ~/programming/engineer_assistant/backend/.venv/bin/python ~/programming/engineer_assistant/backend/run.py --port 8765 > /tmp/ea-backend.log 2>&1 &
```

## antd 组件交互坑

### Select 下拉框
- ❌ `click @option` 会超时
- ❌ `fill @combobox "文本"` 会超时
- ✅ `click @combobox` → `press ArrowDown` → `press Enter`

### Timeline
- ❌ snapshot 不显示 timeline items（没有标准 ARIA role）
- ✅ 用 JS 查 DOM：`document.querySelectorAll('.timeline-item').textContent`

### Spin/Loading
- 交互后 `wait 1000~1500` 等数据加载

## 通用技巧

- 用 `--fn` + `document.title=...` 传递 JS 返回值，再用 `get title --json` 读取
- `network requests` 确认 API 调用是否发出
- 交互后先 `snapshot -i --json` 看 refs，refs 里没有的用 JS 补查
