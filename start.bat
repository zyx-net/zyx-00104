@echo off
echo ========================================
echo 设备校准证书接收与放行服务
echo ========================================
echo.

echo 1. 安装依赖...
pip install -r requirements.txt

echo.
echo 2. 初始化数据库和样例数据...
python init_data.py

echo.
echo 3. 启动服务...
echo 服务地址: http://localhost:5000
echo 按 Ctrl+C 停止服务
echo.
python app.py
