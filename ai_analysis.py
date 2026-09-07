"""
AI 分析模块 - DeepSeek API
个股技术面分析、市场解读、通用问答
"""
import requests
import json
import os
from datetime import datetime

# DeepSeek API 配置（从环境变量读取，密钥保存在 .env 文件中，不提交到代码库）
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

if not DEEPSEEK_API_KEY:
    print("警告: 未配置 DEEPSEEK_API_KEY 环境变量，AI 功能将不可用")

# 系统提示词
SYSTEM_PROMPT = """你是一位专业的A股量化分析师，擅长技术面分析和市场解读。
请基于提供的数据给出客观、简洁的分析，不要模棱两可。
分析时请关注：
1. 当前趋势方向（多头/空头/震荡）
2. 关键支撑位和压力位
3. MACD、均线、成交量等指标信号
4. 短期操作建议（关注/观望/警惕）
5. 风险提示

输出格式要求：
- 先给结论（一句话）
- 再分点说明理由
- 最后给操作建议和风险提示
- 不要使用Markdown表格，用简洁的文字
- 全程用中文"""


def chat_with_deepseek(messages, temperature=0.7, max_tokens=2000):
    """
    调用 DeepSeek 聊天接口
    messages: [{"role": "system"/"user"/"assistant", "content": "..."}]
    """
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    try:
        resp = requests.post(DEEPSEEK_API_URL, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"AI 分析失败：{str(e)}"


def analyze_stock(symbol, name, kline_data, indicator_summary, user_question=None):
    """
    个股 AI 分析
    传入 K 线数据和指标摘要，让 DeepSeek 分析
    """
    latest = indicator_summary["latest"]
    signals = indicator_summary["signals"]
    support = indicator_summary["support"]
    resistance = indicator_summary["resistance"]
    score = indicator_summary["score"]
    trend = indicator_summary["trend"]

    # 辅助函数
    def fmt(v, decimals=2):
        return f"{v:.{decimals}f}" if v is not None else "N/A"

    vol_ratio = (latest['vol_ma5'] / latest['vol_ma20']) if (latest['vol_ma5'] and latest['vol_ma20'] and latest['vol_ma20'] > 0) else None

    # 构造数据摘要
    data_summary = f"""
【股票】{name}（{symbol}）
【最新价】{latest['close']:.2f}（{latest['change_pct']:+.2f}%）
【日期】{latest['date']}

【均线系统】
- MA5: {fmt(latest['ma5'])}
- MA10: {fmt(latest['ma10'])}
- MA20: {fmt(latest['ma20'])}
- MA60: {fmt(latest['ma60'])}

【MACD】
- DIF: {latest['dif']:.4f}
- DEA: {latest['dea']:.4f}
- MACD柱: {latest['macd']:.4f}

【RSI】
- RSI6: {fmt(latest['rsi6'], 1)}
- RSI12: {fmt(latest['rsi12'], 1)}

【成交量】
- 当日: {latest['volume']:.0f}手
- 5日均量: {fmt(latest['vol_ma5'], 0)}手
- 20日均量: {fmt(latest['vol_ma20'], 0)}手
- 量比(5日/20日): {fmt(vol_ratio)}

【技术信号】
{chr(10).join([f"- {s['name']}：{s['desc']}" for s in signals]) if signals else '无明显信号'}

【支撑位】{', '.join([f'{s:.2f}' for s in support]) if support else '暂无'}
【压力位】{', '.join([f'{r:.2f}' for r in resistance]) if resistance else '暂无'}

【综合评分】{score}/100（{trend}）
"""

    # 用户问题
    if user_question:
        user_msg = f"{data_summary}\n\n用户问题：{user_question}\n\n请基于以上数据回答用户问题，并给出你的分析和建议。"
    else:
        user_msg = f"{data_summary}\n\n请基于以上数据，对这只股票进行全面的技术面分析，给出趋势判断、关键价位、操作建议和风险提示。"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    return chat_with_deepseek(messages)


def general_chat(question, context=None):
    """
    通用 AI 问答（市场解读、投资知识等）
    """
    system_prompt = """你是一位专业的A股市场分析师，擅长市场解读、政策分析和投资知识科普。
请用简洁、客观的语言回答问题，不要模棱两可。
如果涉及具体股票，提醒用户需要结合技术面和基本面综合判断。
全程用中文。"""

    user_msg = question
    if context:
        user_msg = f"参考信息：{context}\n\n问题：{question}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    return chat_with_deepseek(messages, temperature=0.8, max_tokens=1500)


def ai_screen_stocks(stocks_data, top_n=5, asset_type="stock"):
    """
    AI 智能选股
    传入一批股票的技术指标数据，让AI分析选出最看好的top_n只
    
    stocks_data: [{"symbol","name","price","change_pct","ma5","ma20","ma60",
                    "dif","dea","macd","rsi6","rsi12","kdj_k","kdj_d","kdj_j",
                    "vol_ratio","score","trend","signals","support","resistance"}]
    asset_type: "stock" 或 "etf"
    """
    if not stocks_data:
        return {"error": "没有股票数据"}

    # 构造数据摘要
    asset_name = "股票" if asset_type == "stock" else "ETF"
    data_lines = []
    for i, s in enumerate(stocks_data, 1):
        signals_str = "、".join([sig.get("name", "") for sig in s.get("signals", [])[:3]]) if s.get("signals") else "无"
        support_str = "、".join([f"{v:.2f}" for v in s.get("support", [])[:2]]) if s.get("support") else "暂无"
        resistance_str = "、".join([f"{v:.2f}" for v in s.get("resistance", [])[:2]]) if s.get("resistance") else "暂无"
        
        line = f"""【{i}】{s.get('name','')}（{s.get('symbol','')}）
- 现价: {s.get('price',0):.2f}（{s.get('change_pct',0):+.2f}%）
- 均线: MA5={s.get('ma5',0):.2f} MA20={s.get('ma20',0):.2f} MA60={s.get('ma60',0):.2f}
- MACD: DIF={s.get('dif',0):.4f} DEA={s.get('dea',0):.4f} 柱={s.get('macd',0):.4f}
- RSI: RSI6={s.get('rsi6',0):.1f} RSI12={s.get('rsi12',0):.1f}
- KDJ: K={s.get('kdj_k',0):.1f} D={s.get('kdj_d',0):.1f} J={s.get('kdj_j',0):.1f}
- 量比: {s.get('vol_ratio',0):.2f}
- 技术信号: {signals_str}
- 支撑位: {support_str}
- 压力位: {resistance_str}
- 综合评分: {s.get('score',0)}/100（{s.get('trend','')}）"""
        data_lines.append(line)

    data_summary = "\n\n".join(data_lines)

    system_prompt = f"""你是一位专业的A股量化分析师，擅长从技术面筛选短期看涨{asset_name}。
你的任务是从提供的{asset_name}列表中，选出后期走势大概率往上的{top_n}只。

选股标准（按重要性排序）：
1. 趋势确认：价格站上MA5/MA20/MA60，均线多头排列
2. MACD信号：DIF>DEA，MACD柱由负转正或持续放大，DIF上穿0轴
3. 量能配合：近期放量上涨，量比>1，资金流入
4. RSI适中：RSI6在40-70之间（不超买也不超卖）
5. KDJ信号：K线上穿D线（金叉），J值在合理区间
6. 技术信号：出现买入信号（金叉、突破、放量等）
7. 综合评分高

输出要求：
- 严格输出JSON格式，不要输出其他文字
- 按看涨概率从高到低排序
- 每只给出：symbol, name, reason（选股理由，50字以内）, target_price（目标价，基于压力位和趋势估算）, stop_loss（止损价，基于支撑位估算）, confidence（看涨信心，0-100）
- 只选{top_n}只，不要多选
- 如果没有符合条件的，返回空数组

JSON格式示例：
{{"picks":[{{"symbol":"sh600519","name":"贵州茅台","reason":"MACD金叉+放量突破+均线多头","target_price":1400,"stop_loss":1280,"confidence":85}}]}}"""

    user_msg = f"""以下是{len(stocks_data)}只{asset_name}的技术指标数据：

{data_summary}

请从中选出最看好的{top_n}只，严格按JSON格式输出。"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    result = chat_with_deepseek(messages, temperature=0, max_tokens=3000)

    # 解析JSON
    try:
        # 提取JSON部分（AI可能输出多余文字）
        import re
        json_match = re.search(r'\{[\s\S]*\}', result)
        if json_match:
            parsed = json.loads(json_match.group())
            return parsed
        else:
            return {"error": "AI返回格式解析失败", "raw": result}
    except Exception as e:
        return {"error": f"解析失败: {str(e)}", "raw": result}
