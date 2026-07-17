# db2http - 数据库数据定时推送服务

`db2http` 是一个轻量级、健壮的数据库数据定时推送工具。它能够从配置文件读取数据库与推送地址配置，定期执行 SQL 查询，并将查询结果以 JSON 格式通过 HTTP POST 发送到指定的 Web 接口（支持分批推送）。

---

## 🌟 核心特性

- 📂 **多数据库支持**：原生支持 **MySQL** 与 **SQLite**，配置简单灵活，无须为本地测试搭建繁琐的 MySQL 环境。
- 🔌 **长连接与复用**：内置连接管理器，自动复用健康的数据库连接；对于 MySQL 自动在推送前执行 `ping(reconnect=True)` 校验，避免频繁建连开销。
- 🛡️ **生产级自愈能力 (Resilience)**：底层捕获网络波动与数据库连接异常，在循环执行模式下若单次任务失败，系统会记录日志并等待下个周期自动重试，而**不会导致守护进程崩溃退出**。
- 🔄 **配置动态热重载**：周期性任务启动前会自动重新加载配置文件，修改 SQL 查询、推送 URL 或推送间隔，无需重启服务即可立即生效。
- 📦 **分批推送功能**：支持配置 `batch_size`，将海量数据切分为指定大小的分批发送，防止单个 HTTP POST 包过大导致网络超时或接收端内存溢出。
- 📝 **结构化日志输出**：集成 Python 标准日志库，自动附带时间戳与日志级别（`INFO` / `WARNING` / `ERROR`）。

---

## 🛠️ 快速开始

### 1. 环境准备
项目基于 Python 3 开发。推荐使用已配置好的虚拟环境。

安装必要依赖：
```bash
# 进入项目根目录
pip install -r requirements.txt  # 或手动安装 pyyaml, requests
# 如果使用 MySQL，请安装 PyMySQL 驱动
pip install pymysql
```

### 2. 配置文件说明 (`db_to_http.yaml`)
配置主要分为 `database` (数据源)、`push` (推送目标) 和 `query` (查询参数) 三部分：

```yaml
# 数据库连接配置
database:
  # 支持 "sqlite" 或 "mysql"
  type: "sqlite"
  
  # SQLite 配置 (如果是 sqlite，database_name 填写 db 文件的路径)
  database_name: "test.db"

  # MySQL 配置 (如果 type 是 mysql，则启用并配置以下参数)
  host: "localhost"
  port: 3306
  user: "root"
  password: "password"
  # database_name: "test_db"
  charset: "utf8mb4"

# 数据推送配置
push:
  url: "http://localhost:8080"    # 数据推送的目标 HTTP 接口地址
  timeout: 10                     # 请求超时时间（秒）
  push_interval: 10               # 循环推送时间间隔（秒），如果不循环或只执行一次请设为 0
  headers:
    Content-Type: "application/json"
    Authorization: "Bearer your_token_here" # 可选，授权 Token

# 查询配置
query:
  sql: "SELECT * FROM test_table LIMIT 10" # 要执行的 SQL 查询语句
  batch_size: 2                            # 分批发送大小（如果为 0 或空，则一次性发送所有数据）

# 日志存储与轮转配置
logging:
  file_enabled: true              # 是否开启日志文件存储
  file_path: "logs/db_to_http.log" # 日志文件路径
  level: "INFO"                   # 日志过滤级别
  rotation_type: "size"           # 轮转策略: "size" (按大小) 或 "time" (按时间)
  max_bytes: 10485760             # 单个文件上限 (10MB)
  backup_count: 5                 # 最大保留历史日志个数
```

### 3. 启动程序
```bash
python db_to_http.py
```

---

## 🧪 本地端到端调试指南

为了方便在本地无数据库和无真实 HTTP 接收端的情况下进行调试，项目中包含了一套闭环测试工具：

### 步骤 A：生成测试 SQLite 数据库
运行数据初始化脚本，在本地生成含有 5 条初始数据的 SQLite 库 `test.db`：
```bash
python init_test_db.py
```

### 步骤 B：启动本地 Mock 接收服务
启动一个监听在 `8080` 端口的简易 HTTP 服务，用于接收并打印推送过去的 JSON 数据包：
```bash
python test_receiver.py
```

### 步骤 C：启动推送工具
运行主程序：
```bash
python db_to_http.py
```
**预期输出：**
* 推送工具会从 `test.db` 中查询出 5 条数据。
* 按照配置文件中的 `batch_size: 2`，分三批次（每批 2 条，最后一批 1 条）发送 HTTP POST 到 Mock 接收端。
* Mock 接收端会实时打印收到的 JSON payload 数据。
* 推送工具在终端输出 `推送成功! 状态码: 200` 并等待下一个周期重新执行。

---

## 📦 打包为独立可执行文件

### 1. 本地打包 (当前系统)
对于您当前的操作系统，您可以使用项目自带的 `build.sh` 脚本进行本地一键打包：
```bash
./build.sh
```
打包成功后，单文件可执行二进制程序将生成在 `dist/` 目录下。

### 2. GitHub Actions 自动化多平台多架构编译
项目已预置了 GitHub Actions 自动化构建工作流 [build.yml](file:///Users/lijilong/project/db2http/.github/workflows/build.yml)。

当您向 GitHub 推送任意版本标签（Git Tag，例如 `v1.0.0`、`v2.0` 等）时，工作流会自动触发，在云端干净的环境中并发编译出以下平台和架构的可执行文件：
- 🐧 **Linux (x86_64)**: `db_to_http-linux-amd64`
- 🪟 **Windows (x86_64)**: `db_to_http-windows-amd64.exe`
- 🍏 **macOS (ARM64 Apple Silicon)**: `db_to_http-macos-arm64`

工作流不仅会在 Actions 运行详情中提供 Artifacts 供下载，还会**自动为您创建一个新的 GitHub Release**，并将编译好的三个二进制文件直接挂载到该 Release 的 Assets 列表中，非常便于版本分发和生产部署。同时，您也可以在 GitHub 项目的 Actions 页面手动点击 `Run workflow` 触发打包。

**💡 运行说明：**
无论在哪个平台运行编译好的可执行程序，均需确保在二进制文件**同级目录**或者当前运行终端的工作路径下存在 `db_to_http.yaml` 配置文件：
```bash
# 测试本地 dist 下的程序
cp db_to_http.yaml dist/
cd dist
./db_to_http
```

---

## 📂 项目结构

```text
├── .github/workflows/
│   └── build.yml      # GitHub Actions 多平台多架构自动打包工作流
├── db_to_http.py      # 主程序逻辑（包含连接管理器、分批推送、日志滚动和动态重载）
├── db_to_http.yaml    # 配置文件（数据库连接、日志参数、HTTP推送及SQL查询）
├── build.sh           # 本地 macOS / Linux 一键打包脚本
├── requirements.txt   # 项目依赖包清单
└── README.md          # 本项目使用说明文档
```
