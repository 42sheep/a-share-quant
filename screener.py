"""
选股引擎
基于成交量、MACD、均线、RSI 等指标筛选 A 股
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from market_data import get_kline, get_realtime_quotes
from indicators import analyze_indicators

# 热门股票池（涵盖各行业龙头，约60只）
HOT_STOCKS = [
    # 白酒/消费
    "sh600519", "sz000858", "sz000568", "sh600809", "sz002304",
    # 银行
    "sh601318", "sz000001", "sh600036", "sh601166", "sh600000",
    # 新能源/光伏
    "sz300750", "sh601012", "sz002594", "sz300274", "sh600438",
    # 科技/半导体
    "sh688981", "sz002475", "sh603501", "sz300782", "sh688012",
    # 医药
    "sh600276", "sz300760", "sh603259", "sz000538", "sh600436",
    # 互联网/传媒
    "sz002624", "sh603444", "sz002555", "sz300413", "sh600637",
    # 地产/基建
    "sh600048", "sz001979", "sh601668", "sh601390", "sh601186",
    # 汽车
    "sh600104", "sz000625", "sh601238", "sz002594",
    # 能源/资源
    "sh601857", "sh600028", "sh601088", "sh600585", "sz000898",
    # 军工
    "sh600760", "sh600893", "sz002179",
    # 农业/食品
    "sh600598", "sz000895", "sh603288", "sz002714",
    # 其他龙头
    "sh601318", "sh600030", "sh601688", "sz000776",
]

# 去重
HOT_STOCKS = list(dict.fromkeys(HOT_STOCKS))

# 主流100只股票池（市值排名前100，从本地JSON加载）
import os
import json
_TOP100_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "top100_stocks.json")
TOP100_STOCKS = []
if os.path.exists(_TOP100_FILE):
    try:
        with open(_TOP100_FILE, "r", encoding="utf-8") as f:
            _top100_data = json.load(f)
            TOP100_STOCKS = [s["symbol"] for s in _top100_data]
    except Exception as e:
        print(f"加载TOP100股票池失败: {e}")
print(f"TOP100股票池加载: {len(TOP100_STOCKS)} 只")


def screen_stocks(stock_list=None, conditions=None, max_workers=8):
    """
    选股主函数
    stock_list: 股票代码列表，默认用热门股票池
    conditions: 筛选条件字典
        - volume_surge: bool，成交量放大（5日均量>20日均量*1.2）
        - macd_gold_cross: bool，MACD金叉或柱转正
        - above_ma20: bool，股价站上20日线
        - rsi_range: [min, max]，RSI6 范围，默认 [30, 70]
        - min_score: int，最低综合评分，默认 10
    返回: [{symbol, name, price, change_pct, score, trend, signals, ...}, ...]
    """
    if stock_list is None:
        stock_list = HOT_STOCKS

    if conditions is None:
        conditions = {}

    # 默认条件
    cond = {
        # 趋势类
        "above_ma20": conditions.get("above_ma20", True),
        "above_ma60": conditions.get("above_ma60", False),
        "ma_bullish": conditions.get("ma_bullish", False),
        "boll_above_mid": conditions.get("boll_above_mid", False),
        # MACD 类
        "macd_gold_cross": conditions.get("macd_gold_cross", True),
        "macd_above_zero": conditions.get("macd_above_zero", False),
        # KDJ 类
        "kdj_gold_cross": conditions.get("kdj_gold_cross", False),
        "kdj_range": conditions.get("kdj_range", [20, 80]),
        # RSI 类
        "rsi_range": conditions.get("rsi_range", [30, 70]),
        # 成交量类
        "volume_surge": conditions.get("volume_surge", True),
        "vol_ratio_min": conditions.get("vol_ratio_min", 1.2),
        # 数值范围类
        "min_score": conditions.get("min_score", 10),
        "turnover_range": conditions.get("turnover_range", None),  # [min, max] %
        "change_pct_range": conditions.get("change_pct_range", None),  # [min, max] %
        "price_range": conditions.get("price_range", None),  # [min, max]
    }

    results = []
    start_time = time.time()

    def process_one(symbol):
        try:
            kline = get_kline(symbol, limit=80)
            if not kline or len(kline) < 30:
                return None

            _, summary = analyze_indicators(kline)
            if summary is None:
                return None

            latest = summary["latest"]
            signals = summary["signals"]
            signal_types = {s["type"] for s in signals}

            # 获取实时行情（用于换手率、涨跌幅、价格等筛选）
            quotes = get_realtime_quotes([symbol])
            quote = quotes[0] if quotes else {}

            # ========== 趋势类条件 ==========
            # 站上 20 日线
            if cond["above_ma20"]:
                if latest["ma20"] and latest["close"] < latest["ma20"]:
                    return None

            # 站上 60 日线
            if cond["above_ma60"]:
                if latest["ma60"] and latest["close"] < latest["ma60"]:
                    return None

            # 均线多头排列
            if cond["ma_bullish"]:
                if "ma_bullish" not in signal_types:
                    return None

            # 布林带站上中轨
            if cond["boll_above_mid"]:
                if latest.get("boll_mid") and latest["close"] < latest["boll_mid"]:
                    return None

            # ========== MACD 类条件 ==========
            # MACD 金叉或柱转正（或多头状态）
            if cond["macd_gold_cross"]:
                if "macd_gold_cross" not in signal_types and "macd_turn_positive" not in signal_types:
                    if not (latest["dif"] and latest["dea"] and latest["macd"] and
                            latest["dif"] > latest["dea"] and latest["macd"] > 0):
                        return None

            # MACD 零轴上方（DIF > 0）
            if cond["macd_above_zero"]:
                if latest["dif"] is None or latest["dif"] <= 0:
                    return None

            # ========== KDJ 类条件 ==========
            # KDJ 金叉
            if cond["kdj_gold_cross"]:
                if "kdj_gold_cross" not in signal_types and "kdj_oversold_gold" not in signal_types:
                    return None

            # KDJ K 值范围
            kdj_min, kdj_max = cond["kdj_range"]
            if latest.get("kdj_k") is not None:
                if latest["kdj_k"] < kdj_min or latest["kdj_k"] > kdj_max:
                    return None

            # ========== RSI 类条件 ==========
            rsi_min, rsi_max = cond["rsi_range"]
            if latest["rsi6"] is not None:
                if latest["rsi6"] < rsi_min or latest["rsi6"] > rsi_max:
                    return None

            # ========== 成交量类条件 ==========
            vol_ratio = None
            if latest["vol_ma5"] and latest["vol_ma20"] and latest["vol_ma20"] > 0:
                vol_ratio = latest["vol_ma5"] / latest["vol_ma20"]

            if cond["volume_surge"]:
                if vol_ratio is None or vol_ratio < cond["vol_ratio_min"]:
                    return None

            # ========== 数值范围类条件 ==========
            # 综合评分
            if summary["score"] < cond["min_score"]:
                return None

            # 换手率范围
            if cond["turnover_range"]:
                t_min, t_max = cond["turnover_range"]
                turnover = quote.get("turnover", 0)
                if turnover < t_min or turnover > t_max:
                    return None

            # 涨跌幅范围
            if cond["change_pct_range"]:
                c_min, c_max = cond["change_pct_range"]
                chg = quote.get("change_pct", latest["change_pct"])
                if chg < c_min or chg > c_max:
                    return None

            # 价格范围
            if cond["price_range"]:
                p_min, p_max = cond["price_range"]
                price = quote.get("price", latest["close"])
                if price < p_min or price > p_max:
                    return None

            return {
                "symbol": symbol,
                "name": quote.get("name", symbol),
                "price": quote.get("price", latest["close"]),
                "change_pct": quote.get("change_pct", latest["change_pct"]),
                "volume": quote.get("volume", latest["volume"]),
                "amount": quote.get("amount", 0),
                "turnover": quote.get("turnover", 0),
                "score": summary["score"],
                "trend": summary["trend"],
                "signals": signals,
                "ma5": latest["ma5"],
                "ma20": latest["ma20"],
                "ma60": latest.get("ma60"),
                "dif": latest["dif"],
                "dea": latest["dea"],
                "macd": latest["macd"],
                "rsi6": latest["rsi6"],
                "kdj_k": latest.get("kdj_k"),
                "kdj_d": latest.get("kdj_d"),
                "boll_mid": latest.get("boll_mid"),
                "vol_ratio": vol_ratio,
            }
        except Exception as e:
            print(f"选股处理失败 {symbol}: {e}")
            return None

    # 并发处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, s): s for s in stock_list}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    # 按评分排序
    results.sort(key=lambda x: x["score"], reverse=True)

    elapsed = time.time() - start_time
    return {
        "total": len(stock_list),
        "matched": len(results),
        "elapsed": round(elapsed, 1),
        "stocks": results,
    }


# ==================== ETF 板块选股 ====================

# 主流ETF列表（宽基+行业+主题，约50只）
ETF_LIST = [
    # 宽基
    {"symbol": "sh510300", "name": "沪深300ETF", "sector": "宽基"},
    {"symbol": "sh510500", "name": "中证500ETF", "sector": "宽基"},
    {"symbol": "sz159915", "name": "创业板ETF", "sector": "宽基"},
    {"symbol": "sh588000", "name": "科创50ETF", "sector": "宽基"},
    {"symbol": "sh510050", "name": "上证50ETF", "sector": "宽基"},
    {"symbol": "sh512100", "name": "中证1000ETF", "sector": "宽基"},
    # 科技/半导体
    {"symbol": "sh512480", "name": "半导体ETF", "sector": "科技"},
    {"symbol": "sh512760", "name": "芯片ETF", "sector": "科技"},
    {"symbol": "sz159819", "name": "人工智能ETF", "sector": "科技"},
    {"symbol": "sh562500", "name": "机器人ETF", "sector": "科技"},
    {"symbol": "sh516510", "name": "云计算ETF", "sector": "科技"},
    {"symbol": "sz159995", "name": "芯片ETF", "sector": "科技"},
    # 新能源
    {"symbol": "sh516160", "name": "新能源ETF", "sector": "新能源"},
    {"symbol": "sh515790", "name": "光伏ETF", "sector": "新能源"},
    {"symbol": "sz159755", "name": "电池ETF", "sector": "新能源"},
    {"symbol": "sh561260", "name": "储能ETF", "sector": "新能源"},
    # 医药
    {"symbol": "sh512010", "name": "医药ETF", "sector": "医药"},
    {"symbol": "sh513120", "name": "创新药ETF", "sector": "医药"},
    {"symbol": "sz159883", "name": "医疗器械ETF", "sector": "医药"},
    # 消费
    {"symbol": "sh510150", "name": "消费ETF", "sector": "消费"},
    {"symbol": "sh512690", "name": "酒ETF", "sector": "消费"},
    {"symbol": "sz159928", "name": "消费ETF", "sector": "消费"},
    # 金融
    {"symbol": "sh512800", "name": "银行ETF", "sector": "金融"},
    {"symbol": "sh512000", "name": "券商ETF", "sector": "金融"},
    {"symbol": "sh512070", "name": "证券保险ETF", "sector": "金融"},
    # 军工/汽车
    {"symbol": "sh512660", "name": "军工ETF", "sector": "军工"},
    {"symbol": "sh516110", "name": "汽车ETF", "sector": "汽车"},
    # 传媒/游戏
    {"symbol": "sh512980", "name": "传媒ETF", "sector": "传媒"},
    {"symbol": "sh516010", "name": "游戏ETF", "sector": "传媒"},
    # 周期/资源
    {"symbol": "sh512400", "name": "有色金属ETF", "sector": "周期"},
    {"symbol": "sh518880", "name": "黄金ETF", "sector": "周期"},
    {"symbol": "sh515220", "name": "煤炭ETF", "sector": "周期"},
    {"symbol": "sh516970", "name": "基建ETF", "sector": "周期"},
    # 地产/家电
    {"symbol": "sh512200", "name": "房地产ETF", "sector": "地产"},
    {"symbol": "sh515220", "name": "家电ETF", "sector": "消费"},
    # 通信/5G
    {"symbol": "sh515050", "name": "5GETF", "sector": "科技"},
    {"symbol": "sz159695", "name": "通信ETF", "sector": "科技"},
    # 农业/环保
    {"symbol": "sz159825", "name": "农业ETF", "sector": "农业"},
    {"symbol": "sh512580", "name": "环保ETF", "sector": "环保"},
    # 中概/港股
    {"symbol": "sh513050", "name": "中概互联ETF", "sector": "港股"},
    {"symbol": "sh513180", "name": "恒生科技ETF", "sector": "港股"},
    # 国企改革/一带一路
    {"symbol": "sh512960", "name": "国企改革ETF", "sector": "主题"},
    {"symbol": "sz159616", "name": "一带一路ETF", "sector": "主题"},
]

# 去重
_etf_seen = set()
ETF_LIST = [e for e in ETF_LIST if not (e["symbol"] in _etf_seen or _etf_seen.add(e["symbol"]))]
print(f"ETF列表加载: {len(ETF_LIST)} 只")


def screen_etfs(max_workers=8):
    """
    ETF板块选股：分析所有ETF的近期表现，按综合评分排序
    返回: {total, matched, elapsed, etfs: [{symbol, name, sector, price, change_pct, chg_5d, chg_20d, chg_60d, vol_ratio, macd_status, rsi6, score, trend, signals}]}
    """
    start_time = time.time()
    results = []

    def process_one(etf):
        try:
            symbol = etf["symbol"]
            # 获取K线
            kline = get_kline(symbol, limit=120)
            if not kline or len(kline) < 30:
                return None

            # 计算指标（返回 (带指标的K线, 汇总字典)）
            _, summary = analyze_indicators(kline)
            if summary is None:
                return None

            latest = summary["latest"]
            signals = summary["signals"]
            signal_types = {s["type"] for s in signals}

            # 近期涨跌幅
            closes = [k["close"] for k in kline]
            current = closes[-1]
            chg_5d = (current / closes[-6] - 1) * 100 if len(closes) >= 6 else 0
            chg_20d = (current / closes[-21] - 1) * 100 if len(closes) >= 21 else 0
            chg_60d = (current / closes[-61] - 1) * 100 if len(closes) >= 61 else 0

            # 实时行情
            quotes = get_realtime_quotes([symbol])
            price = quotes[0]["price"] if quotes else current
            change_pct = quotes[0]["change_pct"] if quotes else latest.get("change_pct", 0)
            turnover = quotes[0]["turnover"] if quotes else 0

            # 技术指标
            dif = latest.get("dif", 0)
            rsi = latest.get("rsi6", 50)
            ma20 = latest.get("ma20", 0)
            ma60 = latest.get("ma60", 0)
            ma5 = latest.get("ma5", 0)
            ma10 = latest.get("ma10", 0)
            macd_bar = latest.get("macd", 0)

            above_ma20 = current > ma20 if ma20 else False
            above_ma60 = current > ma60 if ma60 else False
            ma_bullish = ma5 > ma10 > ma20 if (ma5 and ma10 and ma20) else False
            macd_gold = "macd_gold_cross" in signal_types or macd_bar > 0

            # 量比（5日均量/20日均量）
            volumes = [k["volume"] for k in kline]
            vol_5 = sum(volumes[-5:]) / 5 if len(volumes) >= 5 else 1
            vol_20 = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
            vol_ratio = vol_5 / vol_20 if vol_20 > 0 else 1
            volume_surge = vol_ratio > 1.2

            # KDJ金叉
            kdj_gold = "kdj_gold_cross" in signal_types

            # ETF评分：近期涨幅(40%) + 趋势(30%) + 量能(15%) + 技术指标(15%)
            score = 0
            score += max(min(chg_5d * 3, 30), -10)
            score += max(min(chg_20d * 1.5, 20), -10)
            score += max(min(chg_60d * 0.8, 10), -5)
            if above_ma20:
                score += 10
            if above_ma60:
                score += 8
            if ma_bullish:
                score += 8
            if volume_surge:
                score += 8
            if macd_gold:
                score += 8
            if dif > 0:
                score += 5
            if 40 <= rsi <= 70:
                score += 5

            score = round(score, 1)

            # 趋势判断
            if chg_5d > 3 and chg_20d > 5:
                trend = "强势上涨"
            elif chg_5d > 0 and chg_20d > 0:
                trend = "温和上涨"
            elif chg_5d < -3 and chg_20d < -5:
                trend = "弱势下跌"
            elif chg_5d < 0 and chg_20d < 0:
                trend = "温和下跌"
            else:
                trend = "震荡整理"

            # 技术信号
            sig_list = []
            if macd_gold:
                sig_list.append("MACD金叉")
            if above_ma20:
                sig_list.append("站上20日线")
            if volume_surge:
                sig_list.append("放量")
            if kdj_gold:
                sig_list.append("KDJ金叉")
            if rsi > 70:
                sig_list.append("超买")
            elif rsi < 30:
                sig_list.append("超卖")

            return {
                "symbol": symbol,
                "name": etf["name"],
                "sector": etf["sector"],
                "price": round(price, 4),
                "change_pct": round(change_pct, 2),
                "chg_5d": round(chg_5d, 2),
                "chg_20d": round(chg_20d, 2),
                "chg_60d": round(chg_60d, 2),
                "vol_ratio": round(vol_ratio, 2),
                "dif": round(dif, 4),
                "rsi6": round(rsi, 1),
                "score": score,
                "trend": trend,
                "signals": sig_list,
                "turnover": round(turnover, 2),
            }
        except Exception as e:
            print(f"ETF {etf['symbol']} 分析失败: {e}")
            return None

    # 并发处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, e): e for e in ETF_LIST}
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)

    # 按评分排序
    results.sort(key=lambda x: x["score"], reverse=True)

    elapsed = time.time() - start_time
    return {
        "total": len(ETF_LIST),
        "matched": len(results),
        "elapsed": round(elapsed, 1),
        "etfs": results,
    }
