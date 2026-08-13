"""清空 logs/ 目录下的所有日志文件。"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")


def _delete_files(dir_path: str, suffix: str | None = None) -> int:
    """
删除目录下所有文件（可按后缀过滤），返回删除数量。"""

    count = 0
    if not os.path.isdir(dir_path):
        return count
    for f in os.scandir(dir_path):
        if f.is_file() and (suffix is None or f.name.endswith(suffix)):
            os.remove(f.path)
            count += 1
    return count


def _truncate_files(dir_path: str, suffix: str | None = None) -> int:
    """清空（truncate）目录下所有文件内容，返回处理数量。"""

    count = 0
    if not os.path.isdir(dir_path):
        return count
    for f in os.scandir(dir_path):
        if f.is_file() and (suffix is None or f.name.endswith(suffix)):
            open(f.path, "w").close()
            count += 1
    return count


def clear_logs():
    deleted = 0

    # engine_server: 删除 NDJSON prompt 日志
    deleted += _delete_files(os.path.join(LOGS_DIR, "engine_server"), suffix=".json")

    # server.log / vite.log: 清空内容，保留文件便于继续写入
    deleted += _truncate_files(LOGS_DIR, suffix=".log")

    print(f"完成：清理 {deleted} 个日志文件。")


if __name__ == "__main__":
    clear_logs()
