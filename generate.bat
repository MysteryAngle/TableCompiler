:: ==============================================================================
::  generate.bat
::  双击运行此文件以生成所有配置数据和代码。
:: ==============================================================================
@echo off
setlocal

:: 【代码修正】切换命令提示符到 UTF-8 编码页，以正确显示中文字符。
chcp 65001 > nul

:: 设置标题
title TableCompiler - Generator

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
echo           正在运行 TableCompiler 生成器...
echo =====================================================
echo.

:: 运行 generate 命令
:: 您可以取消下面一行的注释来强制生成，而无需询问
:: python run.py generate --force
python run.py generate %*

echo.
echo =====================================================
echo           操作完成。按任意键退出。
echo =====================================================
echo.
pause
endlocal
