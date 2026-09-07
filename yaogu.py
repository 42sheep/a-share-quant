"""
妖股量化扫描引擎（优化版）
基于量能、连板效应、波动率、小盘特征 + AI 综合分析，预测次日涨停概率
硬性排除：银行/证券/保险、低换手(<2%)、低波动(振幅<3%)、大流通市值(>500亿)
仅供参考，不构成投资建议
"""
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from market_data import get_realtime_quotes, get_kline, get_stock_name
from indicators import analyze_indicators
from ai_analysis import chat_with_deepseek
from screener import TOP100_STOCKS

# 金融板块关键词（硬性排除）
FINANCIAL_KEYWORDS = ["银行", "证券", "保险", "信托", "金融"]


def _is_limit_up(change_pct, is_st=False):
    """判断是否涨停（主板10%，创业板/科创板20%，ST 5%）"""
    threshold = 4.8 if is_st else 9.8
    return change_pct >= threshold


def _is_financial_stock(name):
    """判断是否为金融股（银行/证券/保险等）"""
    if not name:
        return False
    return any(kw in name for kw in FINANCIAL_KEYWORDS)


def _calc_avg_amplitude(kline, days=20):
    """计算近N日平均振幅（(high-low)/prev_close * 100）"""
    if not kline or len(kline) < 5:
        return 0
    recent = kline[-days:] if len(kline) >= days else kline
    amplitudes = []
    for i in range(1, len(recent)):
        prev_close = recent[i-1]["close"]
        if prev_close > 0:
            amp = (recent[i]["high"] - recent[i]["low"]) / prev_close * 100
            amplitudes.append(amp)
    return sum(amplitudes) / len(amplitudes) if amplitudes else 0


def _calc_yaogu_features(quote, kline, indicator_summary, avg_amplitude):
    """计算单只股票的妖股特征分（优化版）"""
    if not kline or len(kline) < 20 or not indicator_summary:
        return None

    name = quote.get("name", "")
    turnover = quote.get("turnover", 0)
    circ_mv = quote.get("circ_mv", 0)  # 流通市值（亿）

    # ===== 硬性排除 =====
    # 1. 金融股（银行/证券/保险）
    if _is_financial_stock(name):
        return None
    # 2. 换手率 < 2%（低换手不可能涨停）
    if turnover < 2:
        return None
    # 3. 近20日平均振幅 < 3%（低波动股）
    if avg_amplitude < 3:
        return None
    # 4. 流通市值 > 500亿（大盘股拉不动）
    if circ_mv > 500:
        return None

    latest = indicator_summary["latest"]
    score = 0
    features = []

    # ===== 1. 量比（加权）=====
    vol_ratio = 1.0
    if latest.get("vol_ma5", 0) > 0:
        vol_ratio = latest["volume"] / latest["vol_ma5"]
    if vol_ratio >= 3:
        score += 25
        features.append(f"巨量(量比{vol_ratio:.1f})")
    elif vol_ratio >= 2:
        score += 15
        features.append(f"放量(量比{vol_ratio:.1f})")
    elif vol_ratio >= 1.5:
        score += 5

    # ===== 2. 换手率（加权）=====
    if turnover >= 15:
        score += 20
        features.append(f"高换手({turnover:.1f}%)")
    elif turnover >= 8:
        score += 12
        features.append(f"换手活跃({turnover:.1f}%)")
    elif turnover >= 4:
        score += 5

    # ===== 3. 近期涨停 / 连板 =====
    recent_limit_ups = 0
    consecutive_limit_ups = 0
    for i in range(min(5, len(kline) - 1)):
        idx = len(kline) - 1 - i
        if kline[idx].get("change_pct", 0) >= 9.8:
            recent_limit_ups += 1
            if i == consecutive_limit_ups:
                consecutive_limit_ups += 1
        else:
            break
    if consecutive_limit_ups >= 3:
        score += 30
        features.append(f"{consecutive_limit_ups}连板")
    elif consecutive_limit_ups >= 2:
        score += 22
        features.append(f"{consecutive_limit_ups}连板")
    elif recent_limit_ups >= 1:
        score += 12
        features.append("近期涨停")

    # ===== 4. 当日涨幅 =====
    change_pct = quote.get("change_pct", 0)
    if change_pct >= 7:
        score += 10
        features.append(f"大涨({change_pct:+.1f}%)")
    elif change_pct >= 3:
        score += 5
    elif change_pct <= -5:
        score -= 15

    # ===== 5. 波动率（新增，妖股核心特征）=====
    if avg_amplitude >= 8:
        score += 15
        features.append(f"高波动(振幅{avg_amplitude:.1f}%)")
    elif avg_amplitude >= 5:
        score += 10
        features.append(f"波动活跃(振幅{avg_amplitude:.1f}%)")
    elif avg_amplitude >= 3.5:
        score += 5

    # ===== 6. 小盘特征（新增）=====
    if 0 < circ_mv <= 50:
        score += 15
        features.append(f"小盘({circ_mv:.0f}亿)")
    elif 50 < circ_mv <= 100:
        score += 10
        features.append(f"中小盘({circ_mv:.0f}亿)")
    elif 100 < circ_mv <= 200:
        score += 5

    # ===== 7. MACD 信号（降权）=====
    dif = latest.get("dif", 0)
    dea = latest.get("dea", 0)
    macd = latest.get("macd", 0)
    if dif > dea and macd > 0:
        score += 5
        features.append("MACD多头")
    elif dif > dea:
        score += 3

    # ===== 8. RSI 强势但不超买 =====
    rsi6 = latest.get("rsi6", 50)
    if 55 <= rsi6 <= 75:
        score += 5
        features.append(f"RSI强势({rsi6:.0f})")
    elif rsi6 > 85:
        score -= 8  # 超买

    # ===== 9. 均线多头（降权，慢牛特征）=====
    ma5 = latest.get("ma5", 0)
    ma10 = latest.get("ma10", 0)
    ma20 = latest.get("ma20", 0)
    if ma5 > ma10 > ma20 and ma5 > 0:
        score += 3
        features.append("均线多头")

    # ===== 10. 突破近期高点 =====
    if len(kline) >= 20:
        recent_high = max(k["high"] for k in kline[-20:-1]) if len(kline) > 20 else kline[-1]["high"]
        if quote.get("high", 0) >= recent_high * 0.99:
            score += 8
            features.append("突破平台")

    score = max(0, min(100, score))

    return {
        "score": score,
        "features": features,
        "vol_ratio": round(vol_ratio, 2),
        "consecutive_limit_ups": consecutive_limit_ups,
        "recent_limit_ups": recent_limit_ups,
        "avg_amplitude": round(avg_amplitude, 2),
        "circ_mv": circ_mv,
    }


def _get_stock_yaogu_data(stock):
    """获取单只股票的妖股分析数据"""
    try:
        symbol = stock["symbol"] if isinstance(stock, dict) else stock
        name = stock.get("name", "") if isinstance(stock, dict) else get_stock_name(symbol)

        # 实时行情
        quotes = get_realtime_quotes([symbol])
        quote = quotes[0] if quotes else {}
        if not quote or quote.get("price", 0) <= 0:
            return None

        # 金融股直接排除
        if _is_financial_stock(quote.get("name", name)):
            return None

        # K线 + 技术指标
        kline = get_kline(symbol, limit=60)
        if not kline or len(kline) < 20:
            return None
        kline_with_ind, summary = analyze_indicators(kline)
        if summary is None:
            return None

        # 计算近20日平均振幅
        avg_amplitude = _calc_avg_amplitude(kline, days=20)

        # 妖股特征（内含硬性排除）
        yaogu = _calc_yaogu_features(quote, kline, summary, avg_amplitude)
        if yaogu is None:
            return None

        latest = summary["latest"]
        return {
            "symbol": symbol,
            "name": quote.get("name", name) or name,
            "price": quote.get("price", 0),
            "change_pct": quote.get("change_pct", 0),
            "turnover": quote.get("turnover", 0),
            "amplitude": quote.get("amplitude", 0),
            "circ_mv": quote.get("circ_mv", 0),
            "volume": quote.get("volume", 0),
            "amount": quote.get("amount", 0),
            "high": quote.get("high", 0),
            "low": quote.get("low", 0),
            "open": quote.get("open", 0),
            "ma5": latest.get("ma5", 0),
            "ma10": latest.get("ma10", 0),
            "ma20": latest.get("ma20", 0),
            "dif": latest.get("dif", 0),
            "dea": latest.get("dea", 0),
            "macd": latest.get("macd", 0),
            "rsi6": latest.get("rsi6", 0),
            "rsi12": latest.get("rsi12", 0),
            "kdj_k": latest.get("kdj_k", 50),
            "kdj_d": latest.get("kdj_d", 50),
            "kdj_j": latest.get("kdj_j", 50),
            "yaogu_score": yaogu["score"],
            "features": yaogu["features"],
            "vol_ratio": yaogu["vol_ratio"],
            "consecutive_limit_ups": yaogu["consecutive_limit_ups"],
            "avg_amplitude": yaogu["avg_amplitude"],
            "signals": summary.get("signals", []),
            "support": summary.get("support", []),
            "resistance": summary.get("resistance", []),
            "trend": summary.get("trend", ""),
        }
    except Exception as e:
        return None


def _ai_yaogu_analysis(candidates, top_n=10):
    """AI 综合分析妖股候选（优化版提示词）"""
    if not candidates:
        return {"error": "没有候选股票"}

    data_lines = []
    for i, s in enumerate(candidates, 1):
        signals_str = "、".join([sig.get("name", "") for sig in s.get("signals", [])[:3]]) if s.get("signals") else "无"
        features_str = "、".join(s.get("features", [])) if s.get("features") else "无明显特征"
        support_str = "、".join([f"{v:.2f}" for v in s.get("support", [])[:2]]) if s.get("support") else "暂无"
        resistance_str = "、".join([f"{v:.2f}" for v in s.get("resistance", [])[:2]]) if s.get("resistance") else "暂无"
        circ_mv = s.get("circ_mv", 0)
        circ_mv_str = f"{circ_mv:.0f}亿" if circ_mv > 0 else "未知"

        line = f"""【{i}】{s.get('name','')}（{s.get('symbol','')}）
- 现价: {s.get('price',0):.2f}（{s.get('change_pct',0):+.2f}%）
- 换手率: {s.get('turnover',0):.1f}%  量比: {s.get('vol_ratio',0):.2f}  流通市值: {circ_mv_str}
- 近20日平均振幅: {s.get('avg_amplitude',0):.1f}%
- 连板数: {s.get('consecutive_limit_ups',0)}
- 妖股特征分: {s.get('yaogu_score',0)}/100
- 核心特征: {features_str}
- 均线: MA5={s.get('ma5',0):.2f} MA10={s.get('ma10',0):.2f} MA20={s.get('ma20',0):.2f}
- MACD: DIF={s.get('dif',0):.4f} DEA={s.get('dea',0):.4f} 柱={s.get('macd',0):.4f}
- RSI: RSI6={s.get('rsi6',0):.1f} RSI12={s.get('rsi12',0):.1f}
- KDJ: K={s.get('kdj_k',0):.1f} D={s.get('kdj_d',0):.1f} J={s.get('kdj_j',0):.1f}
- 技术信号: {signals_str}
- 支撑位: {support_str}
- 压力位: {resistance_str}"""
        data_lines.append(line)

    data_summary = "\n\n".join(data_lines)

    system_prompt = f"""你是一位专业的A股短线交易分析师，擅长捕捉涨停板和妖股机会。
你的任务是从提供的股票列表中，分析每只股票次日涨停的概率，并选出最有可能涨停的{top_n}只。

【重要排除规则】
- 银行、证券、保险等金融股已经被技术过滤，不会出现在列表中
- 低换手率(<2%)、低波动(振幅<3%)、大流通市值(>500亿)的股票已被排除
- 列表中的股票都已具备基本的妖股特征（高换手、高波动、小盘）

【分析维度（按重要性排序）】
1. 连板效应：已有连板的股票有更高连板概率，但3板以上需警惕高位炸板
2. 量能配合：放量上涨是涨停的必要条件，量比>2且换手率>8%为佳
3. 波动率：近20日平均振幅>5%的股票股性活跃，更容易涨停
4. 小盘特征：流通市值<100亿的股票更容易被资金拉动
5. 题材热度：近期涨停过的股票有资金关注度
6. 技术形态：MACD多头、突破平台是加分项，但不是核心（均线多头但低换手的大盘股不是妖股）
7. RSI区间：55-75为强势健康区间，>85超买需警惕

【输出要求】
- 严格输出JSON格式，不要输出其他文字
- 按次日涨停概率从高到低排序
- 每只给出：symbol, name, limit_up_prob（次日涨停概率0-100）, volatility_expected（预期波动幅度，如"高/中/低"）, reason（分析理由，80字以内，必须具体提到量能/换手率/波动率/连板/流通市值等关键因素，不要泛泛而谈）, risk（风险提示，30字以内）
- 只选{top_n}只，不要多选
- 如果没有符合条件的，返回空数组

JSON格式示例：
{{"picks":[{{"symbol":"sz300413","name":"芒果超媒","limit_up_prob":68,"volatility_expected":"高","reason":"换手21%极高+量比2.5+流通市值80亿小盘+2连板，资金关注度极高","risk":"高位炸板风险"}}]}}"""

    user_msg = f"""以下是{len(candidates)}只具备妖股特征的股票技术数据（已排除银行/证券/保险、低换手、低波动、大盘股）：

{data_summary}

请分析每只股票次日涨停的概率，选出最有可能涨停的{top_n}只，严格按JSON格式输出。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    result = chat_with_deepseek(messages, temperature=0.3, max_tokens=4000)

    # 解析JSON
    try:
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            parsed = json.loads(json_match.group())
            return parsed
        else:
            return {"error": "AI返回格式解析失败", "raw": result}
    except Exception as e:
        return {"error": f"解析失败: {str(e)}", "raw": result}


def scan_yaogu(stock_list=None, top_n=10, max_workers=4):
    """
    妖股量化扫描主函数（优化版）
    stock_list: 股票池，默认用 top100
    top_n: AI 最终选出的数量
    返回: {"total_scanned", "total_filtered", "candidates", "picks"}
    """
    if stock_list is None:
        stock_list = TOP100_STOCKS

    # 并发获取所有股票数据（内含硬性过滤）
    all_data = []
    filtered_out = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_get_stock_yaogu_data, s): s for s in stock_list}
        for future in as_completed(futures):
            result = future.result()
            if result:
                all_data.append(result)
            else:
                filtered_out += 1

    if not all_data:
        return {"error": "获取股票数据失败（所有股票均被过滤）", "total_scanned": 0, "total_filtered": filtered_out}

    # 按妖股特征分排序，取前 20 只给 AI 分析
    all_data.sort(key=lambda x: x["yaogu_score"], reverse=True)
    candidates = all_data[:20]

    # AI 综合分析
    ai_result = _ai_yaogu_analysis(candidates, top_n=top_n)

    if "error" in ai_result:
        return {
            "error": ai_result["error"],
            "raw": ai_result.get("raw", ""),
            "total_scanned": len(all_data),
            "total_filtered": filtered_out,
            "candidates": candidates,
            "picks": [],
        }

    picks = ai_result.get("picks", [])

    # 补充每只股票的实时数据
    pick_symbols = [p["symbol"] for p in picks]
    quotes = get_realtime_quotes(pick_symbols) if pick_symbols else []
    quote_map = {q["symbol"]: q for q in quotes}

    for p in picks:
        q = quote_map.get(p["symbol"], {})
        p["price"] = q.get("price", p.get("price", 0))
        p["change_pct"] = q.get("change_pct", 0)
        p["name"] = q.get("name", p.get("name", ""))
        # 从 candidates 里找特征
        c = next((c for c in candidates if c["symbol"] == p["symbol"]), {})
        p["features"] = c.get("features", [])
        p["yaogu_score"] = c.get("yaogu_score", 0)
        p["vol_ratio"] = c.get("vol_ratio", 0)
        p["turnover"] = c.get("turnover", 0)
        p["circ_mv"] = c.get("circ_mv", 0)
        p["avg_amplitude"] = c.get("avg_amplitude", 0)
        p["consecutive_limit_ups"] = c.get("consecutive_limit_ups", 0)

    return {
        "total_scanned": len(all_data),
        "total_filtered": filtered_out,
        "total_candidates": len(candidates),
        "candidates": candidates,
        "picks": picks,
    }
