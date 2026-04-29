@echo off
chcp 65001 >nul
echo ========================================
echo    围棋小课堂 - 一键打包工具
echo ========================================
echo.

:: 检查Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到Python，请先安装Python 3.8+
    pause
    exit /b 1
)

:: 安装可选依赖
echo [1/3] 安装可选依赖（语音功能）...
pip install pyttsx3 pyinstaller -q 2>nul

:: 打包
echo.
echo [2/3] 正在打包...
pyinstaller --onefile --windowed --name "围棋小课堂" main.py

if errorlevel 1 (
    echo [错误] 打包失败
    pause
    exit /b 1
)

:: 清理
echo.
echo [3/3] 清理临时文件...
if exist "build" rmdir /s /q build 2>nul
if exist "*.spec" del *.spec 2>nul

echo.
echo ========================================
echo    打包完成！
echo ========================================
echo.
echo 可执行文件位于: dist\围棋小课堂.exe
echo.
pause
