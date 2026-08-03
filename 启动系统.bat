@echo off
title 中西医结合心血管康复全程管理系统
color 0A

REM ============================================================
REM  中西医结合心血管康复全程管理系统 一键启动
REM  （中医证型 x 心血管危险分层 双轴驱动 | CAD_PCI）
REM  说明：自动定位项目目录、探测 Python（含依赖）、启动系统
REM ============================================================

REM 定位到本文件所在目录（可移植，不依赖绝对路径）
cd /d "%~dp0"

echo.
echo  ==========================================
echo     中西医结合心血管康复全程管理系统
echo     （中医证型 x 心血管危险分层 双轴驱动）
echo  ==========================================
echo.

REM 依赖完整性检查命令（深导入，触发 cryptography 绑定加载）
set "DEP_CHECK=import reportlab, cryptography.hazmat.primitives.ciphers, bcrypt"

set "PYTHON_EXE="

REM ---------- 1. 探测 Python（逐级实测，需依赖完整，避开 Microsoft Store 别名） ----------

REM 1.1 python 命令
python -c "%DEP_CHECK%" >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=python"

REM 1.2 Windows Python Launcher
if not defined PYTHON_EXE (
    py -3 -c "%DEP_CHECK%" >nul 2>nul
    if not errorlevel 1 for /f "delims=" %%x in ('py -3 -c "import sys;print(sys.executable)"') do set "PYTHON_EXE=%%x"
)

REM 1.3 官方安装目录（用户级 + 系统级）
if not defined PYTHON_EXE (
    for /d %%p in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if exist "%%p\python.exe" (
            "%%p\python.exe" -c "%DEP_CHECK%" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%p\python.exe"
        )
    )
)
if not defined PYTHON_EXE (
    for /d %%p in ("C:\Python3*") do (
        if exist "%%p\python.exe" (
            "%%p\python.exe" -c "%DEP_CHECK%" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%p\python.exe"
        )
    )
)

REM 1.4 uv 管理的 Python（优先 3.11 开发环境）
if not defined PYTHON_EXE (
    for /d %%p in ("%USERPROFILE%\AppData\Roaming\uv\python\cpython-3.11*") do (
        if exist "%%p\python.exe" (
            "%%p\python.exe" -c "%DEP_CHECK%" >nul 2>nul
            if not errorlevel 1 set "PYTHON_EXE=%%p\python.exe"
        )
    )
)

REM 1.5 Hermes 开发环境 venv
if not defined PYTHON_EXE (
    if exist "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" (
        "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -c "%DEP_CHECK%" >nul 2>nul
        if not errorlevel 1 set "PYTHON_EXE=%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe"
    )
)

if not defined PYTHON_EXE (
    echo  [错误] 未找到可用的 Python 3.11+（且依赖 reportlab/cryptography/bcrypt）。
    echo         请安装 Python 3.11+（官网 https://www.python.org/downloads/，
    echo         安装时务必勾选 "Add python.exe to PATH"），然后重新运行本文件。
    echo         若已安装 Python，请运行:  python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo  使用 Python: %PYTHON_EXE%
"%PYTHON_EXE%" --version
echo.

REM ---------- 2. 依赖兜底（探测已验依赖，此处仅防探测后被改动） ----------
"%PYTHON_EXE%" -c "%DEP_CHECK%" >nul 2>nul
if errorlevel 1 (
    echo  [提示] 依赖不完整，正在安装（reportlab / cryptography / bcrypt）...
    echo.
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  [错误] 依赖安装失败，请检查网络连接后重新运行本文件。
        echo.
        pause
        exit /b 1
    )
    echo  [完成] 依赖安装成功。
    echo.
)

REM ---------- 3. 启动系统 ----------
echo  [启动] 正在启动系统，请稍候...
echo  [提示] 首次运行请按窗口提示创建管理员账号（用户名/密码）。
echo         数据文件位于 data\rehab.db（请定期手动备份）。
echo.
"%PYTHON_EXE%" app/ui/main.py
if errorlevel 1 (
    echo.
    echo  [错误] 程序异常退出。
    echo         详细错误信息请查看 data\logs\rehab.log
    echo.
    pause
)
