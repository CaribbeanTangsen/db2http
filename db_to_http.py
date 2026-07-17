#!/usr/bin/env script
#!/usr/bin/env python3
"""
数据库数据定时推送工具
从 db_to_http.yaml 读取配置，执行 SQL 查询，并将结果通过 POST 发送到指定 HTTP 地址。
"""

import os
import sys
import time
import json
import datetime
import logging
from decimal import Decimal
import sqlite3
import requests
import yaml
import re

# 自定义异常类
class ConfigurationError(Exception):
    """配置错误"""
    pass

class DatabaseConnectionError(Exception):
    """数据库连接错误"""
    pass

class DatabaseQueryError(Exception):
    """SQL查询错误"""
    pass


def setup_logging(log_config=None):
    """
    动态配置日志，支持控制台输出和基于文件大小/时间周期的日志轮转
    """
    if not log_config:
        log_config = {}

    level_name = log_config.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除旧的 handler 避免重复日志输出
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    # 1. 统一的格式化器
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    # 2. 控制台 Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # 3. 抑制第三方请求库的繁杂日志输出，保持主程序日志可读性
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    # 4. 文件滚动轮转 Handler（如开启）
    if log_config.get("file_enabled", False):
        file_path = log_config.get("file_path", "db_to_http.log")
        rotation_type = log_config.get("rotation_type", "size").lower()
        backup_count = int(log_config.get("backup_count", 5))

        # 确保日志所在目录存在
        log_dir = os.path.dirname(file_path)
        if log_dir and not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir, exist_ok=True)
            except Exception as e:
                logging.error(f"创建日志目录 {log_dir} 失败: {e}")
                return

        if rotation_type == "size":
            from logging.handlers import RotatingFileHandler
            max_bytes = int(log_config.get("max_bytes", 10485760))  # 默认 10MB
            try:
                file_handler = RotatingFileHandler(
                    file_path,
                    maxBytes=max_bytes,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
            except Exception as e:
                logging.error(f"初始化大小滚动日志失败: {e}")
        elif rotation_type == "time":
            from logging.handlers import TimedRotatingFileHandler
            when = log_config.get("when", "D")
            interval = int(log_config.get("interval", 1))
            try:
                file_handler = TimedRotatingFileHandler(
                    file_path,
                    when=when,
                    interval=interval,
                    backupCount=backup_count,
                    encoding='utf-8'
                )
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
            except Exception as e:
                logging.error(f"初始化时间滚动日志失败: {e}")


# 初始化默认的 logger 引用
logger = logging.getLogger("db2http")


# 自定义 JSON 序列化器，用于处理数据库特有的 Decimal, datetime 等数据类型
def json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(obj, datetime.time):
        return obj.strftime('%H:%M:%S')
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, bytes):
        return obj.decode('utf-8', errors='replace')
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


DEFAULT_CONFIG = """# 数据库连接配置
database:
  # 数据库类型，支持 "mysql" 或 "sqlite"
  type: "mysql"
  
  # MySQL 配置 (如果 type 是 mysql，则配置以下参数)
  host: "localhost"
  port: 3306
  user: "root"
  password: "password"
  database_name: "test_db"
  charset: "utf8mb4"

  # SQLite 配置 (如果 type 是 sqlite，database_name 填写 db 文件的路径，例如: "test.db")
  # database_name: "test.db"

# 数据推送配置
push:
  url: "http://httpbin.org/post"  # 默认使用 httpbin 测试地址，可修改为实际推送地址
  timeout: 10                     # 请求超时时间（秒）
  push_interval: 60               # 循环推送时间间隔（秒），如果不循环或只执行一次请设为 0
  headers:
    Content-Type: "application/json"
    Authorization: "Bearer your_token_here" # 可选，授权 Token

# 查询配置
query:
  # 要执行的 SQL 查询语句。支持动态日期/时间占位符，例如：
  # "SELECT * FROM test_table_{today} LIMIT 10" 或者自定义格式 "SELECT * FROM test_table_{today:%Y%m%d} LIMIT 10"
  # 支持的占位符有: {now}, {today}, {yesterday}, {tomorrow}
  sql: "SELECT * FROM test_table LIMIT 10"
  batch_size: 100                          # 分批发送大小（如果为 0 或空，则一次性发送所有数据）

# 日志存储与轮转配置
logging:
  file_enabled: true              # 是否开启日志文件存储
  file_path: "logs/db_to_http.log" # 日志输出的文件路径（目录会自动创建）
  level: "INFO"                   # 日志过滤级别: DEBUG, INFO, WARNING, ERROR
  rotation_type: "size"           # 轮转策略: "size" (按文件大小) 或 "time" (按时间周期)

  # [策略 1] 按大小轮转 (仅在 rotation_type 为 "size" 时有效)
  max_bytes: 10485760             # 每个日志文件大小上限 (10MB = 10 * 1024 * 1024)
  backup_count: 5                 # 保留历史日志文件最大个数

  # [策略 2] 按时间轮转 (仅在 rotation_type 为 "time" 时有效)
  # when: "D"                     # 默认按天轮转
  # interval: 1                   # 间隔数，默认 1天
"""


def load_config(config_path):
    """加载并解析 YAML 配置文件。如果不存在则自动生成默认配置并提示退出。"""
    if not os.path.exists(config_path):
        print(f"提示: 配置文件 '{config_path}' 不存在，正在自动生成默认配置文件...")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(DEFAULT_CONFIG)
            print(f"成功: 默认配置文件 '{config_path}' 已生成！")
            print("请根据实际需求修改该配置文件（例如数据库连接凭证和推送 URL），然后再重新运行本程序。")
            sys.exit(0)
        except Exception as e:
            print(f"错误: 自动生成默认配置文件 '{config_path}' 失败: {e}")
            sys.exit(1)

    with open(config_path, 'r', encoding='utf-8') as f:
        try:
            return yaml.safe_load(f)
        except Exception as e:
            print(f"错误: 无法解析 YAML 配置文件: {e}")
            sys.exit(1)


class DBConnectionManager:
    """数据库连接管理器，负责 MySQL 和 SQLite 连接的获取、保持与释放"""
    def __init__(self, db_config):
        self.db_config = db_config
        self.db_type = db_config.get("type", "sqlite").lower()
        self.conn = None

    def update_config(self, new_db_config):
        """对比并更新配置，若有变更则关闭现有连接以强制重连"""
        if self.db_config != new_db_config:
            logger.info("检测到数据库配置变更，关闭现有连接以应用新配置。")
            self.close()
            self.db_config = new_db_config
            self.db_type = new_db_config.get("type", "sqlite").lower()

    def get_connection(self):
        """获取或重用健康的数据库连接"""
        if self.db_type == "mysql":
            try:
                import pymysql
            except ImportError as e:
                raise ConfigurationError(
                    "未检测到 pymysql 库。请在终端执行以下命令进行安装:\n"
                    "  pip install pymysql\n"
                    "  或者在虚拟环境下:\n"
                    "  .venv/bin/pip install pymysql"
                ) from e

            # 如果已有连接，尝试 ping 检查存活
            if self.conn:
                try:
                    self.conn.ping(reconnect=True)
                    return self.conn
                except Exception:
                    logger.warning("MySQL 连接已断开，尝试重新连接...")
                    self.close()

            # 创建新连接
            try:
                logger.info("正在建立 MySQL 数据库连接...")
                self.conn = pymysql.connect(
                    host=self.db_config.get("host", "localhost"),
                    port=int(self.db_config.get("port", 3306)),
                    user=self.db_config.get("user", "root"),
                    password=str(self.db_config.get("password", "")),
                    database=self.db_config.get("database_name", "test_db"),
                    charset=self.db_config.get("charset", "utf8mb4")
                )
                logger.info("MySQL 数据库连接成功。")
                return self.conn
            except Exception as e:
                raise DatabaseConnectionError(f"连接 MySQL 数据库失败: {e}") from e

        elif self.db_type == "sqlite":
            # 检查 SQLite 连接是否可用
            if self.conn:
                try:
                    self.conn.execute("SELECT 1")
                    return self.conn
                except Exception:
                    logger.warning("SQLite 连接已失效，准备重新连接...")
                    self.close()

            db_path = self.db_config.get("database_name", "test.db")
            try:
                logger.info(f"正在建立 SQLite 数据库连接: {db_path}...")
                self.conn = sqlite3.connect(db_path)
                logger.info("SQLite 数据库连接成功。")
                return self.conn
            except Exception as e:
                raise DatabaseConnectionError(f"连接 SQLite 数据库失败: {e}") from e
        else:
            raise ConfigurationError(f"不支持的数据库类型: {self.db_type}")

    def close(self):
        """关闭当前连接"""
        if self.conn:
            try:
                self.conn.close()
                logger.info("已关闭数据库连接。")
            except Exception as e:
                logger.error(f"关闭数据库连接时发生错误: {e}")
            finally:
                self.conn = None


def query_data(conn, sql):
    """执行 SQL 查询并将结果封装为 dict 列表"""
    logger.info(f"开始执行 SQL 查询: {sql}")
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        # 获取查询结果的列名
        if cursor.description is None:
            logger.info("查询未返回任何结果列（可能执行了非查询语句）。")
            return []

        columns = [desc[0] for desc in cursor.description]

        # 拼装成由 dict 组成的列表
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))

        logger.info(f"查询成功，共获取到 {len(results)} 条数据。")
        return results
    except Exception as e:
        raise DatabaseQueryError(f"执行 SQL 查询失败: {e}") from e
    finally:
        cursor.close()


def send_data(push_config, data_payload):
    """发送 HTTP POST 请求"""
    url = push_config.get("url")
    timeout = push_config.get("timeout", 10)
    headers = push_config.get("headers", {})

    if not url:
        logger.error("错误: 配置文件中未提供推送地址 (push.url)")
        return False

    logger.info(f"正在向 {url} 发送 POST 请求...")
    try:
        # 使用自定义的 json_default 处理 Decimal, datetime 等对象
        json_data = json.dumps(data_payload, default=json_default, ensure_ascii=False)

        # 发送请求，使用 bytes 发送确保编码正确
        response = requests.post(url, data=json_data.encode('utf-8'), headers=headers, timeout=timeout)

        if 200 <= response.status_code < 300:
            logger.info(f"推送成功! 状态码: {response.status_code}")
            try:
                logger.info(f"服务器响应: {response.json()}")
            except Exception:
                logger.info(f"服务器响应: {response.text[:200]}")
            return True
        else:
            logger.error(f"推送失败! 状态码: {response.status_code}")
            logger.error(f"服务器响应: {response.text[:500]}")
            return False
    except Exception as e:
        logger.error(f"推送过程中发生异常: {e}")
        return False
def format_sql(sql_template):
    """
    格式化 SQL 模板中的动态日期/时间占位符。
    支持的占位符:
      - {now} / {now:%Y-%m-%d %H:%M:%S} : 当前时间
      - {today} / {today:%Y-%m-%d} : 今天日期
      - {yesterday} / {yesterday:%Y-%m-%d} : 昨天日期
      - {tomorrow} / {tomorrow:%Y-%m-%d} : 明天日期
    """
    if not sql_template:
        return sql_template

    now = datetime.datetime.now()
    yesterday = now - datetime.timedelta(days=1)
    tomorrow = now + datetime.timedelta(days=1)

    variables = {
        "now": (now, "%Y-%m-%d %H:%M:%S"),
        "today": (now, "%Y-%m-%d"),
        "yesterday": (yesterday, "%Y-%m-%d"),
        "tomorrow": (tomorrow, "%Y-%m-%d")
    }

    pattern = re.compile(r'\{(\w+)(?::([^}]+))?\}')

    def replacer(match):
        var_name = match.group(1).lower()
        format_spec = match.group(2)

        if var_name in variables:
            val, default_format = variables[var_name]
            fmt = format_spec if format_spec is not None else default_format
            try:
                formatted_val = val.strftime(fmt)
                logger.debug(f"解析占位符: {match.group(0)} -> {formatted_val}")
                return formatted_val
            except Exception as e:
                logger.error(f"格式化日期失败: {match.group(0)}, 错误: {e}")
                return match.group(0)
        return match.group(0)

    formatted_sql = pattern.sub(replacer, sql_template)
    if formatted_sql != sql_template:
        logger.info(f"SQL 模板已动态格式化为: {formatted_sql}")
    return formatted_sql


def run_once(db_manager, push_config, query_config):
    # 1. 连接数据库
    conn = db_manager.get_connection()

    # 2. 查询配置
    sql_template = query_config.get("sql")
    if not sql_template:
        raise ConfigurationError("配置文件中未提供查询 SQL (query.sql)")

    # 格式化动态 SQL 语句
    sql = format_sql(sql_template)

    # 3. 执行查询
    data = query_data(conn, sql)

    if not data:
        logger.info("没有查询到数据，无需推送。")
        return

    # 4. 推送数据
    batch_size = query_config.get("batch_size", 0)
    if batch_size and batch_size > 0:
        # 分批推送
        total = len(data)
        logger.info(f"启用分批推送，每批大小 {batch_size}，共 {((total - 1) // batch_size) + 1} 批。")
        for i in range(0, total, batch_size):
            batch = data[i:i+batch_size]
            logger.info(f"--- 正在推送第 {i // batch_size + 1} 批数据 (条数: {len(batch)}) ---")
            success = send_data(push_config, batch)

            if not success:
                logger.error(f"第 {i // batch_size + 1} 批数据推送失败，终止当前任务后续批次的推送。")
                break
    else:
        # 一次性推送全部数据
        send_data(push_config, data)


def main():
    config_path = "db_to_http.yaml"
    config = load_config(config_path)

    # 1. 首次配置并初始化日志模块
    log_config = config.get("logging", {})
    setup_logging(log_config)

    db_config = config.get("database", {})
    push_config = config.get("push", {})
    query_config = config.get("query", {})

    db_manager = DBConnectionManager(db_config)
    push_interval = push_config.get("push_interval", 0)

    try:
        if push_interval and push_interval > 0:
            logger.info(f"已启用循环推送模式，间隔时间: {push_interval} 秒")
            while True:
                try:
                    # 动态重新加载配置文件，使得修改配置无需重启服务
                    config = load_config(config_path)
                    
                    # 热重载日志配置
                    setup_logging(config.get("logging", {}))

                    db_config = config.get("database", {})
                    push_config = config.get("push", {})
                    query_config = config.get("query", {})

                    db_manager.update_config(db_config)

                    # 重新检查推送间隔
                    push_interval = push_config.get("push_interval", 0)
                    if push_interval <= 0:
                        logger.info("检测到循环推送间隔已调整为 0，执行最后一次推送后将退出。")
                        run_once(db_manager, push_config, query_config)
                        break

                    logger.info("开始执行周期性推送任务...")
                    run_once(db_manager, push_config, query_config)

                except (ConfigurationError, DatabaseConnectionError, DatabaseQueryError) as e:
                    logger.error(f"业务执行失败: {e}")
                except Exception as e:
                    logger.exception(f"执行周期任务时发生未捕获的异常: {e}")

                logger.info(f"等待 {push_interval} 秒进行下一次推送...")
                time.sleep(push_interval)
        else:
            logger.info("未配置循环推送间隔时间或间隔为0，仅执行一次推送任务。")
            try:
                run_once(db_manager, push_config, query_config)
            except Exception as e:
                logger.error(f"任务执行失败: {e}")
                sys.exit(1)
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C 中断信号，程序正在优雅退出...")
    finally:
        db_manager.close()


if __name__ == "__main__":
    main()
