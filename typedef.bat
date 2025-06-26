
:: ==============================================================================
::  typedef.bat
::  双击运行此文件以启动交互式的类型定义向导。
:: ==============================================================================
@echo off
setlocal

:: 【代码修正】切换命令提示符到 UTF-8 编码页，以正确显示中文字符。
chcp 65001 > nul

:: 设置标题
title TableCompiler - Typedef Wizard

:: 检查虚拟环境是否存在
if not exist .\.venv\Scripts\activate.bat (
    echo.
    echo 错误: 找不到虚拟环境。
    echo 请先在项目根目录运行 'uv venv' 命令来创建它。
    echo.
    pause
    exit /b 1
)

echo 正在激活虚拟环境...
call .\.venv\Scripts\activate.bat

echo.
echo =====================================================
echo         正在启动 TableCompiler 类型定义向导...
echo =====================================================
echo.

:: 运行 typedef 命令
python run.py typedef

echo.
echo =====================================================
echo           向导已结束。按任意键退出。
echo =====================================================
echo.
pause
endlocal
