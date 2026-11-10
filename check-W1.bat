@echo off
cd /d "%~dp0"
echo.
echo ==========================================
echo  应变 W1 验收：双击即跑
echo ==========================================
echo.
echo [1/2] 规则单元测试（T1-T4 / 接口 / 天气）
python -m unittest discover -s tests
echo.
echo [2/2] 接口实跑巡检（自动起临时服务）
python scripts\acceptance_w1.py --serve
echo.
echo 看到 7/7 项通过 就是 W1 验收 OK
pause
