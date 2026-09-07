"""
回测模块 - 选股结果次日表现统计
记录每次选股结果，自动回测次日红盘率和涨停率
"""
import json
import sqlite3
import os
from datetime import datetime, timedelta
from market_data import get_kline

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stocks.db")


def get_db():
    """获取数据库连接"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_backtest_db():
    """初始化回测相关表"""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS screen_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            screen_date TEXT,
            stocks TEXT,
            backtested INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS backtest_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            name TEXT,
            screen_date TEXT,
            next_trade_date TEXT,
            screen_close REAL,
            next_open REAL,
            next_close REAL,
            change_pct REAL,
            is_red INTEGER,
            is_limit_up INTEGER,
            FOREIGN KEY (record_id) REFERENCES screen_records(id)
        )
    """)
    conn.commit()
    conn.close()


def save_screen_record(record_type, stocks):
    """
    保存选股记录
    record_type: 'yaogu' 或 'ai_screen'
    stocks: [{"symbol": "sh600519", "name": "贵州茅台"}, ...]
    """
    if not stocks:
        return None
    today = datetime.now().strftime("%Y-%m-%d")
    stocks_json = json.dumps(stocks, ensure_ascii=False)
    conn = get_db()
    cursor = conn.execute(
        "INSERT INTO screen_records (type, screen_date, stocks) VALUES (?, ?, ?)",
        (record_type, today, stocks_json)
    )
    record_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return record_id


def _is_limit_up(symbol, change_pct):
    """判断是否涨停（主板10%，创业板/科创板20%，ST 5%）"""
    code = symbol[2:] if len(symbol) > 2 else symbol
    # 创业板 300/301，科创板 688/689
    if code.startswith(("300", "301", "688", "689")):
        threshold = 19.5
    elif code.startswith("8") or code.startswith("4"):
        threshold = 29.5  # 北交所30%
    else:
        threshold = 9.7  # 主板10%（留一点余量）
    return change_pct >= threshold


def _get_next_trade_day_kline(symbol, screen_date):
    """
    获取选股日之后的第一个交易日K线
    返回: (next_date, screen_close, next_open, next_close) 或 None
    """
    try:
        kline = get_kline(symbol, limit=10)
        if not kline or len(kline) < 2:
            return None

        # 找到选股日在K线中的位置
        screen_idx = None
        for i, k in enumerate(kline):
            if k["date"] == screen_date:
                screen_idx = i
                break

        # 如果选股日不在K线中（可能是节假日/周末），找最近的一个交易日
        if screen_idx is None:
            # 找小于等于选股日的最近交易日
            for i in range(len(kline) - 1, -1, -1):
                if kline[i]["date"] <= screen_date:
                    screen_idx = i
                    break
            if screen_idx is None:
                return None

        # 选股日收盘价
        screen_close = kline[screen_idx]["close"]

        # 下一个交易日
        if screen_idx + 1 >= len(kline):
            return None  # 还没有次日数据

        next_k = kline[screen_idx + 1]
        return (next_k["date"], screen_close, next_k["open"], next_k["close"])
    except Exception as e:
        print(f"回测获取K线失败 {symbol}: {e}")
        return None


def run_backtest_for_record(record_id):
    """对单条选股记录执行回测"""
    conn = get_db()
    record = conn.execute("SELECT * FROM screen_records WHERE id = ?", (record_id,)).fetchone()
    if not record:
        conn.close()
        return {"error": "记录不存在"}
    if record["backtested"]:
        conn.close()
        return {"error": "已回测", "record_id": record_id}

    stocks = json.loads(record["stocks"])
    screen_date = record["screen_date"]
    results = []

    for stock in stocks:
        symbol = stock["symbol"]
        name = stock.get("name", "")
        bt = _get_next_trade_day_kline(symbol, screen_date)
        if bt is None:
            continue
        next_date, screen_close, next_open, next_close = bt
        change_pct = (next_close - screen_close) / screen_close * 100 if screen_close > 0 else 0
        is_red = 1 if change_pct > 0 else 0
        is_limit_up = 1 if _is_limit_up(symbol, change_pct) else 0

        conn.execute("""
            INSERT INTO backtest_results
            (record_id, symbol, name, screen_date, next_trade_date,
             screen_close, next_open, next_close, change_pct, is_red, is_limit_up)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (record_id, symbol, name, screen_date, next_date,
              screen_close, next_open, next_close, round(change_pct, 2), is_red, is_limit_up))
        results.append({
            "symbol": symbol, "name": name, "change_pct": round(change_pct, 2),
            "is_red": is_red, "is_limit_up": is_limit_up
        })

    if results:
        conn.execute("UPDATE screen_records SET backtested = 1 WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()

    return {
        "record_id": record_id,
        "screen_date": screen_date,
        "total": len(results),
        "red_count": sum(r["is_red"] for r in results),
        "limit_up_count": sum(r["is_limit_up"] for r in results),
        "avg_change": round(sum(r["change_pct"] for r in results) / len(results), 2) if results else 0,
        "results": results,
    }


def run_pending_backtests():
    """回测所有未回测且已有次日数据的记录"""
    conn = get_db()
    pending = conn.execute("SELECT id FROM screen_records WHERE backtested = 0 ORDER BY id").fetchall()
    conn.close()

    backtested = []
    skipped = []
    for record in pending:
        result = run_backtest_for_record(record["id"])
        if "error" in result and result["error"] == "已回测":
            continue
        if result.get("total", 0) > 0:
            backtested.append(result)
        else:
            skipped.append(record["id"])

    return {
        "backtested_count": len(backtested),
        "skipped_count": len(skipped),
        "details": backtested,
    }


def get_backtest_stats(record_type=None):
    """
    获取回测统计
    record_type: None=全部, 'yaogu'=妖股选股, 'ai_screen'=AI选股
    """
    conn = get_db()
    query = """
        SELECT br.*, sr.type as record_type
        FROM backtest_results br
        JOIN screen_records sr ON br.record_id = sr.id
        WHERE sr.backtested = 1
    """
    params = []
    if record_type:
        query += " AND sr.type = ?"
        params.append(record_type)
    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return {
            "total_stocks": 0,
            "red_count": 0,
            "limit_up_count": 0,
            "red_rate": 0,
            "limit_up_rate": 0,
            "avg_change": 0,
            "record_count": 0,
        }

    total = len(rows)
    red_count = sum(r["is_red"] for r in rows)
    limit_up_count = sum(r["is_limit_up"] for r in rows)
    avg_change = sum(r["change_pct"] for r in rows) / total

    # 记录次数
    record_ids = set(r["record_id"] for r in rows)

    return {
        "total_stocks": total,
        "red_count": red_count,
        "limit_up_count": limit_up_count,
        "red_rate": round(red_count / total * 100, 1),
        "limit_up_rate": round(limit_up_count / total * 100, 1),
        "avg_change": round(avg_change, 2),
        "record_count": len(record_ids),
    }


def get_backtest_history(record_type=None, limit=20):
    """获取回测历史记录列表"""
    conn = get_db()
    query = "SELECT * FROM screen_records WHERE backtested = 1"
    params = []
    if record_type:
        query += " AND type = ?"
        params.append(record_type)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    records = conn.execute(query, params).fetchall()

    history = []
    for rec in records:
        results = conn.execute(
            "SELECT * FROM backtest_results WHERE record_id = ?", (rec["id"],)
        ).fetchall()
        total = len(results)
        red_count = sum(r["is_red"] for r in results)
        limit_up_count = sum(r["is_limit_up"] for r in results)
        avg_change = sum(r["change_pct"] for r in results) / total if total else 0

        history.append({
            "record_id": rec["id"],
            "type": rec["type"],
            "screen_date": rec["screen_date"],
            "total": total,
            "red_count": red_count,
            "limit_up_count": limit_up_count,
            "red_rate": round(red_count / total * 100, 1) if total else 0,
            "limit_up_rate": round(limit_up_count / total * 100, 1) if total else 0,
            "avg_change": round(avg_change, 2),
            "stocks": [{"symbol": r["symbol"], "name": r["name"],
                         "change_pct": r["change_pct"], "is_red": r["is_red"],
                         "is_limit_up": r["is_limit_up"]} for r in results],
        })
    conn.close()
    return history


def get_pending_records():
    """获取待回测的记录"""
    conn = get_db()
    records = conn.execute(
        "SELECT * FROM screen_records WHERE backtested = 0 ORDER BY id DESC"
    ).fetchall()
    conn.close()
    result = []
    for rec in records:
        stocks = json.loads(rec["stocks"])
        result.append({
            "record_id": rec["id"],
            "type": rec["type"],
            "screen_date": rec["screen_date"],
            "stock_count": len(stocks),
            "stocks": stocks,
        })
    return result
