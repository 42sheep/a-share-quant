"""
A股量化分析系统 - Flask 主程序
简洁版：自选股监控 + 个股分析 + AI投研 + 选股参考
"""
import os
import json
import sqlite3
from flask import Flask, render_template, request, jsonify, g

# 启动时加载 .env 环境变量（密钥等敏感配置，不提交到代码库）
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    try:
        with open(_env_path, encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    os.environ.setdefault(_k.strip(), _v.strip())
    except Exception as _e:
        print(f".env 加载失败: {_e}")

from market_data import get_realtime_quotes, get_kline, get_stock_name, validate_symbol, search_stock
from indicators import analyze_indicators
from ai_analysis import analyze_stock, general_chat, ai_screen_stocks
from screener import screen_stocks, HOT_STOCKS, TOP100_STOCKS, screen_etfs, ETF_LIST

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stocks.db")


def get_db():
    """获取数据库连接"""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """关闭数据库连接"""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT UNIQUE NOT NULL,
            name TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # 默认添加几只热门股票
    defaults = ["sh600519", "sz000001", "sh601318", "sz300750", "sh601857"]
    for s in defaults:
        try:
            conn.execute("INSERT OR IGNORE INTO watchlist (symbol, name) VALUES (?, ?)", (s, None))
        except:
            pass
    conn.commit()
    conn.close()


# ============ 页面路由 ============

@app.route("/")
def index():
    """首页 - 自选股监控"""
    return render_template("index.html")


@app.route("/stock/<symbol>")
def stock_detail(symbol):
    """个股详情页"""
    return render_template("stock.html", symbol=symbol)


@app.route("/screener")
def screener_page():
    """选股页"""
    return render_template("screener.html")


@app.route("/etf")
def etf_page():
    """ETF板块选股页"""
    return render_template("etf.html")


# ============ API 路由 ============

@app.route("/api/watchlist", methods=["GET"])
def get_watchlist():
    """获取自选股列表（含实时行情）"""
    db = get_db()
    rows = db.execute("SELECT symbol, name FROM watchlist ORDER BY added_at").fetchall()
    symbols = [r["symbol"] for r in rows]

    if not symbols:
        return jsonify({"stocks": []})

    # 获取实时行情
    quotes = get_realtime_quotes(symbols)
    quote_map = {q["symbol"]: q for q in quotes}

    result = []
    for r in rows:
        q = quote_map.get(r["symbol"], {})
        result.append({
            "symbol": r["symbol"],
            "name": q.get("name") or r["name"] or r["symbol"],
            "price": q.get("price", 0),
            "change_pct": q.get("change_pct", 0),
            "change": q.get("change", 0),
            "volume": q.get("volume", 0),
            "amount": q.get("amount", 0),
            "turnover": q.get("turnover", 0),
            "high": q.get("high", 0),
            "low": q.get("low", 0),
            "open": q.get("open", 0),
        })

    return jsonify({"stocks": result})


@app.route("/api/watchlist", methods=["POST"])
def add_watchlist():
    """添加自选股"""
    data = request.get_json()
    symbol = validate_symbol(data.get("symbol", ""))
    if not symbol:
        return jsonify({"error": "股票代码格式不正确，示例：sh600519 或 600519"}), 400

    name = get_stock_name(symbol)
    db = get_db()
    try:
        db.execute("INSERT OR IGNORE INTO watchlist (symbol, name) VALUES (?, ?)", (symbol, name))
        db.commit()
        return jsonify({"success": True, "symbol": symbol, "name": name})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/watchlist/<symbol>", methods=["DELETE"])
def remove_watchlist(symbol):
    """删除自选股"""
    db = get_db()
    db.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
    db.commit()
    return jsonify({"success": True})


@app.route("/api/search")
def api_search():
    """股票联想搜索（支持中文名称、拼音、代码）"""
    keyword = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 10))
    if not keyword:
        return jsonify({"results": []})
    results = search_stock(keyword, limit=limit)
    return jsonify({"results": results})


@app.route("/api/quote")
def api_quote():
    """获取实时行情"""
    symbols = request.args.get("symbols", "").split(",")
    symbols = [s.strip() for s in symbols if s.strip()]
    if not symbols:
        return jsonify({"error": "请提供股票代码"}), 400

    quotes = get_realtime_quotes(symbols)
    return jsonify({"quotes": quotes})


@app.route("/api/kline")
def api_kline():
    """获取K线数据"""
    symbol = request.args.get("symbol", "")
    limit = int(request.args.get("limit", 120))
    symbol = validate_symbol(symbol)
    if not symbol:
        return jsonify({"error": "股票代码格式不正确"}), 400

    kline = get_kline(symbol, limit=limit)
    return jsonify({"symbol": symbol, "kline": kline})


@app.route("/api/indicators")
def api_indicators():
    """获取技术指标分析"""
    symbol = request.args.get("symbol", "")
    limit = int(request.args.get("limit", 120))
    symbol = validate_symbol(symbol)
    if not symbol:
        return jsonify({"error": "股票代码格式不正确"}), 400

    kline = get_kline(symbol, limit=limit)
    kline_with_indicators, summary = analyze_indicators(kline)

    if summary is None:
        return jsonify({"error": "数据不足，无法计算指标"}), 400

    return jsonify({
        "symbol": symbol,
        "name": get_stock_name(symbol),
        "summary": summary,
        "kline": kline_with_indicators,
    })


@app.route("/api/ai/analyze", methods=["POST"])
def api_ai_analyze():
    """AI 个股分析"""
    data = request.get_json()
    symbol = validate_symbol(data.get("symbol", ""))
    question = data.get("question", "")

    if not symbol:
        return jsonify({"error": "股票代码格式不正确"}), 400

    # 获取数据
    kline = get_kline(symbol, limit=80)
    _, summary = analyze_indicators(kline)
    if summary is None:
        return jsonify({"error": "数据不足，无法进行AI分析"}), 400

    name = get_stock_name(symbol)
    result = analyze_stock(symbol, name, kline, summary, question)

    return jsonify({
        "symbol": symbol,
        "name": name,
        "analysis": result,
        "summary": summary,
    })


@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    """通用 AI 问答"""
    data = request.get_json()
    question = data.get("question", "")
    if not question:
        return jsonify({"error": "请输入问题"}), 400

    result = general_chat(question)
    return jsonify({"answer": result})


@app.route("/api/screener/run", methods=["POST"])
def api_screener_run():
    """执行选股"""
    data = request.get_json() or {}
    conditions = data.get("conditions", {})
    stock_list = data.get("stocks")  # None 则用默认热门池
    pool = data.get("pool")

    # 根据 pool 选择股票池
    if pool == "top100":
        stock_list = TOP100_STOCKS
    elif pool == "hot":
        stock_list = HOT_STOCKS
    # pool 为 watchlist/custom 时，stock_list 由前端传入

    result = screen_stocks(stock_list=stock_list, conditions=conditions)
    return jsonify(result)


@app.route("/api/screener/hot")
def api_screener_hot():
    """获取热门股票池列表"""
    quotes = get_realtime_quotes(HOT_STOCKS[:30])  # 只返回前30只的行情
    return jsonify({"total": len(HOT_STOCKS), "stocks": quotes})


@app.route("/api/etf/screen")
def api_etf_screen():
    """ETF板块选股"""
    result = screen_etfs()
    return jsonify(result)


@app.route("/api/ai/screen", methods=["POST"])
def api_ai_screen():
    """AI 智能选股 - 技术初筛 + AI综合分析"""
    data = request.get_json() or {}
    pool = data.get("pool", "top100")
    top_n = int(data.get("top_n", 5))
    custom_stocks = data.get("stocks")

    # 选择股票池
    if pool == "etf":
        stock_list = [{"symbol": e["symbol"], "name": e["name"]} for e in ETF_LIST]
        asset_type = "etf"
    elif pool == "top100":
        stock_list = TOP100_STOCKS
        asset_type = "stock"
    elif pool == "hot":
        stock_list = HOT_STOCKS
        asset_type = "stock"
    elif pool == "watchlist":
        # 从数据库获取自选股
        db = get_db()
        rows = db.execute("SELECT symbol, name FROM watchlist ORDER BY created_at DESC").fetchall()
        stock_list = [{"symbol": r["symbol"], "name": r["name"]} for r in rows]
        asset_type = "stock"
    elif custom_stocks:
        stock_list = custom_stocks
        asset_type = "stock"
    else:
        stock_list = TOP100_STOCKS
        asset_type = "stock"

    if not stock_list:
        return jsonify({"error": "股票池为空"}), 400

    # 批量获取技术指标（并发）
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def get_stock_data(s):
        try:
            symbol = s["symbol"] if isinstance(s, dict) else s
            name = s.get("name", "") if isinstance(s, dict) else get_stock_name(symbol)
            kline = get_kline(symbol, limit=120)
            if not kline or len(kline) < 30:
                return None
            _, summary = analyze_indicators(kline)
            latest = summary["latest"]

            # 量比
            vol_ratio = (latest.get("vol_ma5", 0) / latest.get("vol_ma20", 1)) if latest.get("vol_ma20", 0) > 0 else 1

            return {
                "symbol": symbol,
                "name": name,
                "price": latest.get("close", 0),
                "change_pct": latest.get("change_pct", 0),
                "ma5": latest.get("ma5", 0),
                "ma10": latest.get("ma10", 0),
                "ma20": latest.get("ma20", 0),
                "ma60": latest.get("ma60", 0),
                "dif": latest.get("dif", 0),
                "dea": latest.get("dea", 0),
                "macd": latest.get("macd", 0),
                "rsi6": latest.get("rsi6", 0),
                "rsi12": latest.get("rsi12", 0),
                "kdj_k": latest.get("kdj_k", 50),
                "kdj_d": latest.get("kdj_d", 50),
                "kdj_j": latest.get("kdj_j", 50),
                "vol_ratio": vol_ratio,
                "score": summary.get("score", 0),
                "trend": summary.get("trend", ""),
                "signals": summary.get("signals", []),
                "support": summary.get("support", []),
                "resistance": summary.get("resistance", []),
            }
        except Exception as e:
            return None

    stocks_data = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(get_stock_data, s): s for s in stock_list}
        for future in as_completed(futures):
            result = future.result()
            if result:
                stocks_data.append(result)

    if not stocks_data:
        return jsonify({"error": "获取股票数据失败"}), 500

    # 按综合评分排序，取前15只给AI分析
    stocks_data.sort(key=lambda x: x["score"], reverse=True)
    candidates = stocks_data[:15]

    # 调用AI选股
    ai_result = ai_screen_stocks(candidates, top_n=top_n, asset_type=asset_type)

    if "error" in ai_result:
        return jsonify({"error": ai_result["error"], "raw": ai_result.get("raw", "")}), 500

    picks = ai_result.get("picks", [])

    # 补充每只股票的实时数据
    pick_symbols = [p["symbol"] for p in picks]
    quotes = get_realtime_quotes(pick_symbols) if pick_symbols else {}
    quote_map = {q["symbol"]: q for q in quotes} if isinstance(quotes, list) else quotes

    for p in picks:
        q = quote_map.get(p["symbol"], {})
        p["price"] = q.get("price", p.get("price", 0))
        p["change_pct"] = q.get("change_pct", 0)
        p["name"] = q.get("name", p.get("name", ""))

    return jsonify({
        "total_candidates": len(candidates),
        "total_scanned": len(stocks_data),
        "picks": picks,
        "asset_type": asset_type,
    })


if __name__ == "__main__":
    init_db()
    # 端口：Render.com 通过 PORT 环境变量指定，本地默认 5050
    port = int(os.environ.get("PORT", 5050))
    # 获取局域网IP（仅本地运行时显示）
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
    
    print("=" * 50)
    print("A股量化分析系统启动中...")
    print(f"本机访问: http://127.0.0.1:{port}")
    if port == 5050:
        print(f"手机访问(同WiFi): http://{local_ip}:{port}")
    print("=" * 50)
    app.run(host="0.0.0.0", port=port, debug=False)
