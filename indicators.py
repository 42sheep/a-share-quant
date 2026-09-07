"""
技术指标计算模块（纯 Python 实现，无 pandas/numpy 依赖）
MA、MACD、RSI、成交量均线、支撑压力位
"""


def calc_ma(close_list, periods=[5, 10, 20, 60]):
    """计算移动平均线，返回 {period: [values]}"""
    result = {}
    n = len(close_list)
    for p in periods:
        ma = [None] * n
        for i in range(p - 1, n):
            ma[i] = sum(close_list[i-p+1:i+1]) / p
        result[f"ma{p}"] = ma
    return result


def calc_ema(values, period):
    """计算指数移动平均"""
    n = len(values)
    ema = [None] * n
    if n == 0:
        return ema
    k = 2 / (period + 1)
    ema[0] = values[0]
    for i in range(1, n):
        ema[i] = values[i] * k + ema[i-1] * (1 - k)
    return ema


def calc_macd(close_list, fast=12, slow=26, signal=9):
    """计算 MACD，返回 (dif_list, dea_list, macd_hist_list)"""
    ema_fast = calc_ema(close_list, fast)
    ema_slow = calc_ema(close_list, slow)
    n = len(close_list)
    dif = [None] * n
    for i in range(n):
        if ema_fast[i] is not None and ema_slow[i] is not None:
            dif[i] = ema_fast[i] - ema_slow[i]

    # DEA = EMA(DIF, signal)
    valid_dif = [d if d is not None else 0 for d in dif]
    dea_full = calc_ema(valid_dif, signal)
    dea = [None] * n
    for i in range(n):
        if dif[i] is not None:
            dea[i] = dea_full[i]

    macd_hist = [None] * n
    for i in range(n):
        if dif[i] is not None and dea[i] is not None:
            macd_hist[i] = (dif[i] - dea[i]) * 2  # 通达信风格

    return dif, dea, macd_hist


def calc_rsi(close_list, periods=[6, 12, 24]):
    """计算 RSI，返回 {period: [values]}"""
    result = {}
    n = len(close_list)
    delta = [0] * n
    for i in range(1, n):
        delta[i] = close_list[i] - close_list[i-1]

    for p in periods:
        rsi = [None] * n
        if n <= p:
            result[f"rsi{p}"] = rsi
            continue

        # 初始平均
        avg_gain = sum(max(d, 0) for d in delta[1:p+1]) / p
        avg_loss = sum(max(-d, 0) for d in delta[1:p+1]) / p

        if avg_loss == 0:
            rsi[p] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[p] = 100 - (100 / (1 + rs))

        # 平滑计算
        for i in range(p + 1, n):
            gain = max(delta[i], 0)
            loss = max(-delta[i], 0)
            avg_gain = (avg_gain * (p - 1) + gain) / p
            avg_loss = (avg_loss * (p - 1) + loss) / p
            if avg_loss == 0:
                rsi[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi[i] = 100 - (100 / (1 + rs))

        result[f"rsi{p}"] = rsi
    return result


def calc_volume_ma(volume_list, periods=[5, 20]):
    """计算成交量均线"""
    result = {}
    n = len(volume_list)
    for p in periods:
        ma = [None] * n
        for i in range(p - 1, n):
            ma[i] = sum(volume_list[i-p+1:i+1]) / p
        result[f"vol_ma{p}"] = ma
    return result


def calc_kdj(kline_data, n=9, m1=3, m2=3):
    """
    计算 KDJ 指标
    返回 (k_list, d_list, j_list)
    """
    close_list = [d["close"] for d in kline_data]
    high_list = [d["high"] for d in kline_data]
    low_list = [d["low"] for d in kline_data]
    length = len(kline_data)

    k = [None] * length
    d = [None] * length
    j = [None] * length

    if length < n:
        return k, d, j

    # 计算 RSV
    rsv = [None] * length
    for i in range(n - 1, length):
        highest = max(high_list[i-n+1:i+1])
        lowest = min(low_list[i-n+1:i+1])
        if highest == lowest:
            rsv[i] = 50.0
        else:
            rsv[i] = (close_list[i] - lowest) / (highest - lowest) * 100

    # K = 2/3 * 前K + 1/3 * RSV，初始 K=50
    # D = 2/3 * 前D + 1/3 * K，初始 D=50
    prev_k = 50.0
    prev_d = 50.0
    for i in range(n - 1, length):
        if rsv[i] is None:
            continue
        k[i] = (m1 - 1) / m1 * prev_k + 1 / m1 * rsv[i]
        d[i] = (m2 - 1) / m2 * prev_d + 1 / m2 * k[i]
        j[i] = 3 * k[i] - 2 * d[i]
        prev_k = k[i]
        prev_d = d[i]

    return k, d, j


def calc_boll(close_list, period=20, std_dev=2):
    """
    计算布林带
    返回 (mid, upper, lower)
    """
    n = len(close_list)
    mid = [None] * n
    upper = [None] * n
    lower = [None] * n

    for i in range(period - 1, n):
        window = close_list[i-period+1:i+1]
        m = sum(window) / period
        variance = sum((x - m) ** 2 for x in window) / period
        sd = variance ** 0.5
        mid[i] = m
        upper[i] = m + std_dev * sd
        lower[i] = m - std_dev * sd

    return mid, upper, lower


def find_support_resistance(kline_data, window=20):
    """找支撑位和压力位"""
    recent = kline_data[-window:] if len(kline_data) > window else kline_data
    if len(recent) < 5:
        return {"support": [], "resistance": []}

    lows = [d["low"] for d in recent]
    highs = [d["high"] for d in recent]

    support_candidates = []
    for i in range(2, len(lows) - 2):
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            support_candidates.append(lows[i])

    resistance_candidates = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            resistance_candidates.append(highs[i])

    def merge_levels(levels, threshold=0.02):
        if not levels:
            return []
        levels = sorted(set(levels))
        merged = [levels[0]]
        for l in levels[1:]:
            if (l - merged[-1]) / merged[-1] > threshold:
                merged.append(l)
        return merged

    return {
        "support": merge_levels(support_candidates)[:3],
        "resistance": merge_levels(resistance_candidates)[:3],
    }


def analyze_indicators(kline_data):
    """
    综合分析技术指标
    输入: [{date, open, close, high, low, volume}, ...]
    输出: (kline_with_indicators, summary)
    """
    if not kline_data or len(kline_data) < 30:
        return None, {}

    # 按日期排序
    kline_data = sorted(kline_data, key=lambda x: x["date"])

    close_list = [d["close"] for d in kline_data]
    volume_list = [d["volume"] for d in kline_data]
    n = len(kline_data)

    # 计算指标
    ma = calc_ma(close_list)
    dif, dea, macd_hist = calc_macd(close_list)
    rsi = calc_rsi(close_list)
    vol_ma = calc_volume_ma(volume_list)
    kdj_k, kdj_d, kdj_j = calc_kdj(kline_data)
    boll_mid, boll_upper, boll_lower = calc_boll(close_list)

    # 合并到每条K线
    kline_with_indicators = []
    for i, d in enumerate(kline_data):
        item = dict(d)
        for k, v in ma.items():
            item[k] = v[i]
        item["dif"] = dif[i]
        item["dea"] = dea[i]
        item["macd"] = macd_hist[i]
        for k, v in rsi.items():
            item[k] = v[i]
        for k, v in vol_ma.items():
            item[k] = v[i]
        item["kdj_k"] = kdj_k[i]
        item["kdj_d"] = kdj_d[i]
        item["kdj_j"] = kdj_j[i]
        item["boll_mid"] = boll_mid[i]
        item["boll_upper"] = boll_upper[i]
        item["boll_lower"] = boll_lower[i]
        kline_with_indicators.append(item)

    # 最新数据
    latest = kline_with_indicators[-1]
    prev = kline_with_indicators[-2] if n > 1 else latest

    # 信号判断
    signals = []

    # MACD 金叉/死叉
    if (prev["dif"] is not None and prev["dea"] is not None and
        latest["dif"] is not None and latest["dea"] is not None):
        if prev["dif"] <= prev["dea"] and latest["dif"] > latest["dea"]:
            signals.append({"type": "macd_gold_cross", "name": "MACD金叉", "strength": "strong", "desc": "DIF上穿DEA，短期多头信号"})
        elif prev["dif"] >= prev["dea"] and latest["dif"] < latest["dea"]:
            signals.append({"type": "macd_death_cross", "name": "MACD死叉", "strength": "strong", "desc": "DIF下穿DEA，短期空头信号"})

    # MACD 柱由负转正/由正转负
    if prev["macd"] is not None and latest["macd"] is not None:
        if prev["macd"] <= 0 and latest["macd"] > 0:
            signals.append({"type": "macd_turn_positive", "name": "MACD柱转正", "strength": "medium", "desc": "MACD柱状图由负转正，多头动能增强"})
        elif prev["macd"] >= 0 and latest["macd"] < 0:
            signals.append({"type": "macd_turn_negative", "name": "MACD柱转负", "strength": "medium", "desc": "MACD柱状图由正转负，空头动能增强"})

    # 均线多头/空头排列
    if all(latest.get(f"ma{p}") is not None for p in [5, 10, 20]):
        if latest["ma5"] > latest["ma10"] > latest["ma20"]:
            signals.append({"type": "ma_bullish", "name": "均线多头排列", "strength": "medium", "desc": "5日>10日>20日均线，短期趋势向上"})
        elif latest["ma5"] < latest["ma10"] < latest["ma20"]:
            signals.append({"type": "ma_bearish", "name": "均线空头排列", "strength": "medium", "desc": "5日<10日<20日均线，短期趋势向下"})

    # 股价站上/跌破 20 日均线
    if latest.get("ma20") is not None and prev.get("ma20") is not None:
        if prev["close"] <= prev["ma20"] and latest["close"] > latest["ma20"]:
            signals.append({"type": "above_ma20", "name": "站上20日线", "strength": "medium", "desc": "股价突破20日均线，中期趋势转强"})
        elif prev["close"] >= prev["ma20"] and latest["close"] < latest["ma20"]:
            signals.append({"type": "below_ma20", "name": "跌破20日线", "strength": "medium", "desc": "股价跌破20日均线，中期趋势转弱"})

    # 成交量放大
    if latest.get("vol_ma5") and latest.get("vol_ma20") and latest["vol_ma20"] > 0:
        vol_ratio = latest["vol_ma5"] / latest["vol_ma20"]
        if vol_ratio > 1.5:
            signals.append({"type": "volume_surge", "name": "成交量放大", "strength": "medium", "desc": f"5日均量是20日均量的{vol_ratio:.1f}倍，资金关注度提升"})

    # RSI 超买/超卖
    if latest.get("rsi6") is not None:
        if latest["rsi6"] > 80:
            signals.append({"type": "rsi_overbought", "name": "RSI超买", "strength": "weak", "desc": f"RSI6={latest['rsi6']:.1f}，短期超买，注意回调风险"})
        elif latest["rsi6"] < 20:
            signals.append({"type": "rsi_oversold", "name": "RSI超卖", "strength": "weak", "desc": f"RSI6={latest['rsi6']:.1f}，短期超卖，可能有反弹机会"})

    # KDJ 金叉/死叉/超卖区金叉
    if (latest.get("kdj_k") is not None and latest.get("kdj_d") is not None and
        prev.get("kdj_k") is not None and prev.get("kdj_d") is not None):
        if prev["kdj_k"] <= prev["kdj_d"] and latest["kdj_k"] > latest["kdj_d"]:
            if latest["kdj_k"] < 30:
                signals.append({"type": "kdj_oversold_gold", "name": "KDJ超卖金叉", "strength": "strong", "desc": f"K={latest['kdj_k']:.1f}上穿D={latest['kdj_d']:.1f}，且在超卖区，反弹信号强"})
            else:
                signals.append({"type": "kdj_gold_cross", "name": "KDJ金叉", "strength": "medium", "desc": f"K={latest['kdj_k']:.1f}上穿D={latest['kdj_d']:.1f}，短期多头信号"})
        elif prev["kdj_k"] >= prev["kdj_d"] and latest["kdj_k"] < latest["kdj_d"]:
            if latest["kdj_k"] > 70:
                signals.append({"type": "kdj_overbought_death", "name": "KDJ超买死叉", "strength": "strong", "desc": f"K={latest['kdj_k']:.1f}下穿D={latest['kdj_d']:.1f}，且在超买区，回调风险大"})
            else:
                signals.append({"type": "kdj_death_cross", "name": "KDJ死叉", "strength": "medium", "desc": f"K={latest['kdj_k']:.1f}下穿D={latest['kdj_d']:.1f}，短期空头信号"})

    # 布林带信号
    if latest.get("boll_mid") is not None and latest.get("boll_upper") is not None:
        if prev["close"] <= prev["boll_upper"] and latest["close"] > latest["boll_upper"]:
            signals.append({"type": "boll_break_upper", "name": "突破布林上轨", "strength": "medium", "desc": f"股价突破上轨{latest['boll_upper']:.2f}，强势但注意超买"})
        elif prev["close"] >= prev["boll_mid"] and latest["close"] < latest["boll_mid"]:
            signals.append({"type": "boll_below_mid", "name": "跌破布林中轨", "strength": "medium", "desc": f"股价跌破中轨{latest['boll_mid']:.2f}，中期转弱"})
        elif prev["close"] <= prev["boll_mid"] and latest["close"] > latest["boll_mid"]:
            signals.append({"type": "boll_above_mid", "name": "站上布林中轨", "strength": "weak", "desc": f"股价站上中轨{latest['boll_mid']:.2f}，中期转强"})

    # 支撑压力位
    sr = find_support_resistance(kline_data)

    # 综合评分
    score = 0
    for s in signals:
        weight = {"strong": 20, "medium": 10, "weak": 5}.get(s["strength"], 5)
        is_bullish = any(kw in s["name"] for kw in ["金叉", "多头", "站上", "放大", "转正", "超卖"])
        score += weight if is_bullish else -weight
    score = max(-100, min(100, score))

    change_pct = ((latest["close"] - prev["close"]) / prev["close"] * 100) if prev["close"] > 0 else 0

    summary = {
        "latest": {
            "date": latest["date"],
            "close": latest["close"],
            "change_pct": change_pct,
            "ma5": latest.get("ma5"),
            "ma10": latest.get("ma10"),
            "ma20": latest.get("ma20"),
            "ma60": latest.get("ma60"),
            "dif": latest.get("dif"),
            "dea": latest.get("dea"),
            "macd": latest.get("macd"),
            "rsi6": latest.get("rsi6"),
            "rsi12": latest.get("rsi12"),
            "volume": latest["volume"],
            "vol_ma5": latest.get("vol_ma5"),
            "vol_ma20": latest.get("vol_ma20"),
            "kdj_k": latest.get("kdj_k"),
            "kdj_d": latest.get("kdj_d"),
            "kdj_j": latest.get("kdj_j"),
            "boll_mid": latest.get("boll_mid"),
            "boll_upper": latest.get("boll_upper"),
            "boll_lower": latest.get("boll_lower"),
        },
        "signals": signals,
        "support": sr["support"],
        "resistance": sr["resistance"],
        "score": score,
        "trend": "偏多" if score > 20 else ("偏空" if score < -20 else "震荡"),
    }

    return kline_with_indicators, summary
