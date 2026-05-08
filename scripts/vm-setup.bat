@echo off
:: Forge 后端快速测试环境 (Windows VM)
:: 用法：双击运行，或 powershell 里执行
:: 前提：已安装 Python 3.12+ 和 Git

echo === Forge 后端测试环境搭建 ===
echo.

:: 1. 创建工作目录
if not exist "C:\forge-test" mkdir "C:\forge-test"
cd /d "C:\forge-test"

:: 2. 克隆代码（或从宿主机共享目录拷贝）
if not exist "backend" (
    echo 正在克隆代码...
    git clone https://github.com/Chris-behind-door/Forge.git repo
    mklink /D backend repo\backend
) else (
    echo 代码已存在，跳过克隆
)

cd backend

:: 3. 创建 venv
if not exist ".venv" (
    echo 正在创建虚拟环境...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

:: 4. 安装依赖
echo 正在安装依赖...
pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple

:: 5. 下载 embedding 模型（可选，需要网络）
echo.
echo === 环境准备完成 ===
echo.
echo 启动后端：
echo   cd C:\forge-test\backend
echo   .venv\Scripts\activate
echo   python -m uvicorn src.main:app --host 127.0.0.1 --port 8765
echo.
echo 前端连接：在浏览器打开 Tauri 应用，或直接访问 http://127.0.0.1:8765/docs 测试 API
echo.
pause
