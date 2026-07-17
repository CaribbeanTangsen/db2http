#!/bin/bash

# 确保遇到错误立即终止运行
set -e

# 日志颜色输出
green() { echo -e "\033[32m$1\033[0m"; }
blue() { echo -e "\033[34m$1\033[0m"; }

blue "=== 1. 正在检查并准备打包环境 ==="

# 检测并激活虚拟环境
if [ -d ".venv" ]; then
    blue "检测到虚拟环境 .venv，正在激活..."
    source .venv/bin/activate
else
    blue "未检测到本地虚拟环境 .venv，使用当前系统环境 Python。"
fi

# 安装基础依赖与 PyInstaller
blue "正在升级 pip 并安装依赖..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

blue "=== 2. 开始使用 PyInstaller 进行打包 ==="
# --onefile: 打包为独立单文件可执行程序
# --clean: 清除打包缓存
# --name: 指定最终生成的可执行文件文件名
pyinstaller --onefile --clean --name db_to_http db_to_http.py

green "=== 3. 打包成功！ ==="
green "Standalone 可执行文件已生成在: dist/db_to_http"
echo ""
echo "⚠️  注意: 运行可执行文件时，需要确保其同级目录或工作目录下存在 'db_to_http.yaml' 配置文件。"
echo "你可以运行以下命令测试新生成的可执行文件："
echo "  cp db_to_http.yaml dist/"
echo "  cd dist && ./db_to_http"
echo ""
