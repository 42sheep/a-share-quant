"""
服务器状态与应用统计采集模块
用于后台管理仪表盘
"""
import os
import time
import sqlite3
import subprocess
from datetime import datetime, timedelta


def get_server_stats():
    """获取服务器整体状态"""
    return {
        'cpu': get_cpu_usage(),
        'memory': get_memory_usage(),
        'disk': get_disk_usage(),
        'load': get_load_average(),
        'uptime': get_uptime(),
        'process_count': get_process_count(),
        'gunicorn_workers': get_gunicorn_workers(),
        'network': get_network_stats(),
    }


def get_cpu_usage():
    """通过两次采样 /proc/stat 计算 CPU 使用率"""
    try:
        def read_cpu():
            with open('/proc/stat', 'r') as f:
                parts = f.readline().split()
            idle = int(parts[4])
            total = sum(int(x) for x in parts[1:])
            return idle, total

        idle1, total1 = read_cpu()
        time.sleep(0.5)
        idle2, total2 = read_cpu()

        idle_diff = idle2 - idle1
        total_diff = total2 - total1
        if total_diff == 0:
            return 0
        usage = (1 - idle_diff / total_diff) * 100
        return round(usage, 1)
    except Exception:
        return 0


def get_memory_usage():
    """读取 /proc/meminfo 获取内存使用"""
    try:
        mem = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(':')
                value_kb = int(parts[1])
                if key == 'MemTotal':
                    mem['total_mb'] = round(value_kb / 1024, 0)
                elif key == 'MemAvailable':
                    mem['available_mb'] = round(value_kb / 1024, 0)
                elif key == 'MemFree':
                    mem['free_mb'] = round(value_kb / 1024, 0)
                elif key == 'Buffers':
                    mem['buffers_mb'] = round(value_kb / 1024, 0)
                elif key == 'Cached':
                    mem['cached_mb'] = round(value_kb / 1024, 0)

        total = mem.get('total_mb', 0)
        available = mem.get('available_mb', mem.get('free_mb', 0))
        used = total - available
        mem['used_mb'] = round(used, 0)
        mem['percent'] = round(used / total * 100, 1) if total > 0 else 0
        return mem
    except Exception:
        return {'total_mb': 0, 'used_mb': 0, 'percent': 0}


def get_disk_usage():
    """通过 os.statvfs 获取根分区磁盘使用"""
    try:
        stat = os.statvfs('/')
        total_gb = stat.f_blocks * stat.f_frsize / (1024 ** 3)
        free_gb = stat.f_bavail * stat.f_frsize / (1024 ** 3)
        used_gb = total_gb - free_gb
        return {
            'total_gb': round(total_gb, 1),
            'used_gb': round(used_gb, 1),
            'free_gb': round(free_gb, 1),
            'percent': round(used_gb / total_gb * 100, 1) if total_gb > 0 else 0,
        }
    except Exception:
        return {'total_gb': 0, 'used_gb': 0, 'percent': 0}


def get_load_average():
    """读取 /proc/loadavg"""
    try:
        with open('/proc/loadavg', 'r') as f:
            parts = f.read().split()
        return {
            '1min': float(parts[0]),
            '5min': float(parts[1]),
            '15min': float(parts[2]),
        }
    except Exception:
        return {'1min': 0, '5min': 0, '15min': 0}


def get_uptime():
    """读取 /proc/uptime 计算系统运行时长"""
    try:
        with open('/proc/uptime', 'r') as f:
            seconds = float(f.read().split()[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        return {
            'seconds': int(seconds),
            'days': days,
            'hours': hours,
            'minutes': minutes,
            'formatted': f'{days}天{hours}小时{minutes}分',
        }
    except Exception:
        return {'formatted': '未知'}


def get_process_count():
    """统计 /proc 下的进程数"""
    try:
        count = 0
        for name in os.listdir('/proc'):
            if name.isdigit():
                count += 1
        return count
    except Exception:
        return 0


def get_gunicorn_workers():
    """统计 gunicorn 进程数（1主 + N worker）"""
    try:
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True, text=True, timeout=5
        )
        count = 0
        for line in result.stdout.split('\n'):
            if 'gunicorn' in line and 'grep' not in line:
                count += 1
        return count
    except Exception:
        return 0


def get_network_stats():
    """读取 /proc/net/dev 获取网络流量"""
    try:
        with open('/proc/net/dev', 'r') as f:
            lines = f.readlines()

        total_rx = 0
        total_tx = 0
        for line in lines[2:]:
            parts = line.split()
            if len(parts) >= 10:
                iface = parts[0].rstrip(':')
                if iface in ('lo', 'docker0'):
                    continue
                rx_bytes = int(parts[1])
                tx_bytes = int(parts[9])
                total_rx += rx_bytes
                total_tx += tx_bytes

        return {
            'rx_mb': round(total_rx / (1024 ** 2), 1),
            'tx_mb': round(total_tx / (1024 ** 2), 1),
            'total_mb': round((total_rx + total_tx) / (1024 ** 2), 1),
        }
    except Exception:
        return {'rx_mb': 0, 'tx_mb': 0, 'total_mb': 0}


def get_access_stats(db_path):
    """从访问日志表统计访问数据"""
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()

        # 总访问量
        c.execute('SELECT COUNT(*) FROM access_logs')
        total = c.fetchone()[0]

        # 今日访问
        today = datetime.now().strftime('%Y-%m-%d')
        c.execute("SELECT COUNT(*) FROM access_logs WHERE date(created_at) = ?", (today,))
        today_count = c.fetchone()[0]

        # 独立 IP
        c.execute('SELECT COUNT(DISTINCT ip) FROM access_logs')
        unique_ips = c.fetchone()[0]

        # 热门页面 TOP10
        c.execute('''
            SELECT path, COUNT(*) as cnt
            FROM access_logs
            WHERE path NOT LIKE '/api/%'
            GROUP BY path
            ORDER BY cnt DESC
            LIMIT 10
        ''')
        top_pages = [{'path': r[0], 'count': r[1]} for r in c.fetchall()]

        # 最近24小时访问趋势（按小时）
        c.execute('''
            SELECT strftime('%Y-%m-%d %H:00', created_at) as hour, COUNT(*) as cnt
            FROM access_logs
            WHERE created_at >= datetime('now', '-24 hours')
            GROUP BY hour
            ORDER BY hour
        ''')
        hourly = [{'hour': r[0], 'count': r[1]} for r in c.fetchall()]

        # 最近20条访问记录
        c.execute('''
            SELECT ip, path, method, status, created_at
            FROM access_logs
            ORDER BY id DESC
            LIMIT 20
        ''')
        recent = [dict(r) for r in c.fetchall()]

        conn.close()
        return {
            'total': total,
            'today': today_count,
            'unique_ips': unique_ips,
            'top_pages': top_pages,
            'hourly': hourly,
            'recent': recent,
        }
    except Exception as e:
        return {'total': 0, 'today': 0, 'unique_ips': 0, 'top_pages': [], 'hourly': [], 'recent': [], 'error': str(e)}


def get_app_stats(db_path):
    """应用层面统计"""
    stats = {}
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()

        # 自选股数
        try:
            c.execute('SELECT COUNT(*) FROM watchlist')
            stats['watchlist_count'] = c.fetchone()[0]
        except Exception:
            stats['watchlist_count'] = 0

        # 回测记录数
        try:
            c.execute('SELECT COUNT(*) FROM screen_records')
            stats['screen_record_count'] = c.fetchone()[0]
        except Exception:
            stats['screen_record_count'] = 0

        # 回测完成数
        try:
            c.execute('SELECT COUNT(*) FROM backtest_results')
            stats['backtest_result_count'] = c.fetchone()[0]
        except Exception:
            stats['backtest_result_count'] = 0

        # 访问日志数
        try:
            c.execute('SELECT COUNT(*) FROM access_logs')
            stats['access_log_count'] = c.fetchone()[0]
        except Exception:
            stats['access_log_count'] = 0

        conn.close()
    except Exception:
        pass

    # 数据库大小
    try:
        if os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            stats['db_size_kb'] = round(size_bytes / 1024, 1)
            stats['db_size_mb'] = round(size_bytes / (1024 ** 2), 2)
    except Exception:
        stats['db_size_kb'] = 0

    return stats


def init_access_log_db(db_path):
    """初始化访问日志表"""
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ip TEXT,
                path TEXT,
                method TEXT,
                status INTEGER DEFAULT 200,
                user_agent TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_access_created ON access_logs(created_at)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_access_path ON access_logs(path)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_access_ip ON access_logs(ip)')
        conn.commit()
        conn.close()
    except Exception:
        pass
