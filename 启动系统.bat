@echo off
title 中西医结合心血管康复全程管理系统
color 0A

REM ============================================================
REM  中西医结合心血管康复全程管理系统 一键启动
REM  （中医证型 x 心血管危险分层 双轴驱动 | CAD_PCI）
REM  说明：自动定位项目目录、检查 Python 与依赖、启动系统
REM ============================================================

REM 定位到本文件所在目录（可移植，不依赖绝对路径）
cd /d "%~dp0"

echo.
echo  ==========================================
echo     中西医结合心血管康复全程管理系统
echo     （中医证型 x 心血管危险分层 双轴驱动）
echo  ==========================================
echo.

REM ---------- 1. 检查 Python ----------
where python >nul 2>nul
if errorlevel 1 (
    echo  [错误] 未找到 python 命令。
    echo         请安装 Python 3.11+ 并勾选 "Add python.exe to PATH"，然后重试。
    echo.
    pause
    exit /b 1
)

REM ---------- 2. 检查运行依赖（reportlab / cryptography / bcrypt） ----------
python -c "import reportlab, cryptography, bcrypt" >nul 2>nul
if errorlevel 1 (
    echo  [提示] 首次运行，正在安装依赖（reportlab / cryptography / bcrypt）...
    echo.
    python -m pip install -r requirements.txt
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
python app/ui/main.py
if errorlevel 1 (
    echo.
    echo  [错误] 程序异常退出。
    echo         详细错误信息请查看 data\logs\rehab.log
    echo.
    pause
)
