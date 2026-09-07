"""
行情数据模块 - 腾讯财经数据源
免费、国内访问快，支持 A 股实时行情和日K数据
"""
import requests
import time
import json
from datetime import datetime

# 腾讯财经实时行情接口
QUOTE_URL = "http://qt.gtimg.cn/q={symbols}"
# 腾讯财经日K接口（前复权）
KLINE_URL = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{limit},qfq"
# 东方财富日K接口（备用数据源，前复权）
EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57&klt=101&fqt=1&end=20500101&lmt={limit}"
# 新浪日K接口（第三备用源）
SINA_KLINE_URL = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen={limit}"

# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "http://gu.qq.com/",
}

# 缓存
_quote_cache = {}
_quote_cache_time = {}
_CACHE_TTL = 5  # 实时行情缓存5秒

# K线缓存（10分钟，避免重复请求触发风控）
_kline_cache = {}
_kline_cache_time = {}
_KLINE_CACHE_TTL = 600


def get_realtime_quotes(symbols):
    """
    批量获取实时行情
    symbols: ['sh600519', 'sz000001', ...]
    返回: [{symbol, name, price, change, change_pct, open, high, low, prev_close, volume, amount, turnover}, ...]
    """
    if not symbols:
        return []

    # 检查缓存
    now = time.time()
    cached = []
    need_fetch = []
    for s in symbols:
        if s in _quote_cache and (now - _quote_cache_time.get(s, 0)) < _CACHE_TTL:
            cached.append(_quote_cache[s])
        else:
            need_fetch.append(s)

    if need_fetch:
        try:
            url = QUOTE_URL.format(symbols=",".join(need_fetch))
            resp = requests.get(url, headers=HEADERS, timeout=5)
            resp.encoding = "gbk"
            text = resp.text

            for line in text.strip().split("\n"):
                if "=" not in line:
                    continue
                parts = line.split("=", 1)
                if len(parts) < 2:
                    continue
                symbol = parts[0].replace("v_", "").strip()
                data_str = parts[1].strip().strip('";')
                fields = data_str.split("~")

                if len(fields) < 35:
                    continue

                try:
                    quote = {
                        "symbol": symbol,
                        "name": fields[1],
                        "code": fields[2],
                        "price": float(fields[3]) if fields[3] else 0,
                        "prev_close": float(fields[4]) if fields[4] else 0,
                        "open": float(fields[5]) if fields[5] else 0,
                        "volume": float(fields[6]) if fields[6] else 0,  # 手
                        "high": float(fields[33]) if fields[33] else 0,
                        "low": float(fields[34]) if fields[34] else 0,
                        "change": float(fields[31]) if fields[31] else 0,
                        "change_pct": float(fields[32]) if fields[32] else 0,
                        "amount": float(fields[37]) if fields[37] else 0,  # 万元
                        "turnover": float(fields[38]) if len(fields) > 38 and fields[38] else 0,  # 换手率%
                    }
                    _quote_cache[symbol] = quote
                    _quote_cache_time[symbol] = now
                    cached.append(quote)
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"获取实时行情失败: {e}")

    return cached


def _get_kline_tencent(symbol, limit):
    """腾讯K线接口"""
    try:
        url = KLINE_URL.format(symbol=symbol, limit=limit)
        resp = requests.get(url, headers=HEADERS, timeout=8)
        data = resp.json()

        # 解析数据
        stock_data = data.get("data", {}).get(symbol, {})
        kline_data = stock_data.get("qfqday") or stock_data.get("day") or []

        result = []
        for item in kline_data:
            if len(item) < 6:
                continue
            result.append({
                "date": item[0],
                "open": float(item[1]),
                "close": float(item[2]),
                "high": float(item[3]),
                "low": float(item[4]),
                "volume": float(item[5]),
            })
        return result
    except Exception as e:
        print(f"腾讯K线失败 {symbol}: {e}")
        return []


def _symbol_to_secid(symbol):
    """sh600519 -> 1.600519, sz000001 -> 0.000001"""
    if symbol.startswith("sh"):
        return "1." + symbol[2:]
    elif symbol.startswith("sz"):
        return "0." + symbol[2:]
    return symbol


def _get_kline_eastmoney(symbol, limit):
    """东方财富K线接口（备用）"""
    for attempt in range(2):
        try:
            secid = _symbol_to_secid(symbol)
            url = EM_KLINE_URL.format(secid=secid, limit=limit)
            em_headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://quote.eastmoney.com/",
            }
            resp = requests.get(url, headers=em_headers, timeout=8)
            data = resp.json()

            klines = data.get("data", {}).get("klines", [])
            result = []
            for item in klines:
                # 格式: "2024-01-02,开盘,收盘,最高,最低,成交量,成交额"
                fields = item.split(",")
                if len(fields) < 6:
                    continue
                result.append({
                    "date": fields[0],
                    "open": float(fields[1]),
                    "close": float(fields[2]),
                    "high": float(fields[3]),
                    "low": float(fields[4]),
                    "volume": float(fields[5]),
                })
            if result:
                return result
            time.sleep(0.5)
        except Exception as e:
            if attempt == 0:
                time.sleep(0.5)
            else:
                print(f"东财K线失败 {symbol}: {e}")
    return []


def _get_kline_sina(symbol, limit):
    """新浪K线接口（第三备用源）"""
    try:
        url = SINA_KLINE_URL.format(symbol=symbol, limit=limit)
        sina_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/",
        }
        resp = requests.get(url, headers=sina_headers, timeout=8)
        data = resp.json()

        result = []
        for item in data:
            # 格式: {"day":"2024-01-02","open":"1680.00","high":"1685.00","low":"1655.00","close":"1670.00","volume":"4541600"}
            result.append({
                "date": item.get("day", ""),
                "open": float(item.get("open", 0)),
                "close": float(item.get("close", 0)),
                "high": float(item.get("high", 0)),
                "low": float(item.get("low", 0)),
                "volume": float(item.get("volume", 0)),
            })
        return result
    except Exception as e:
        print(f"新浪K线失败 {symbol}: {e}")
        return []


def get_kline(symbol, limit=120):
    """
    获取日K线数据（前复权）
    返回: [{date, open, close, high, low, volume}, ...] 按日期升序
    数据源顺序：腾讯 → 东方财富 → 新浪，10分钟缓存
    """
    # 缓存检查
    now = time.time()
    if symbol in _kline_cache and (now - _kline_cache_time.get(symbol, 0)) < _KLINE_CACHE_TTL:
        return _kline_cache[symbol]

    # 腾讯优先
    result = _get_kline_tencent(symbol, limit)
    # 失败则东方财富备用
    if not result:
        result = _get_kline_eastmoney(symbol, limit)
    # 再失败则新浪
    if not result:
        result = _get_kline_sina(symbol, limit)

    if result:
        _kline_cache[symbol] = result
        _kline_cache_time[symbol] = now
    return result


def get_stock_name(symbol):
    """获取股票名称"""
    quotes = get_realtime_quotes([symbol])
    if quotes:
        return quotes[0]["name"]
    return symbol


def validate_symbol(symbol):
    """验证股票代码格式"""
    symbol = symbol.strip().lower()
    if symbol.startswith("sh") and len(symbol) == 8 and symbol[2:].isdigit():
        return symbol
    if symbol.startswith("sz") and len(symbol) == 8 and symbol[2:].isdigit():
        return symbol
    # 尝试自动补全
    if len(symbol) == 6 and symbol.isdigit():
        if symbol.startswith("6"):
            return "sh" + symbol
        elif symbol.startswith(("0", "3")):
            return "sz" + symbol
    return None


# 腾讯财经智能搜索接口
SEARCH_URL = "https://smartbox.gtimg.cn/s3/?q={keyword}&t=all"

# 搜索结果缓存
_search_cache = {}


def search_stock(keyword, limit=10):
    """
    股票联想搜索（支持中文名称、拼音、代码）
    返回: [{symbol, name, code, pinyin, market}, ...]
    """
    keyword = keyword.strip()
    if not keyword:
        return []

    # 检查缓存
    cache_key = keyword.lower()
    if cache_key in _search_cache:
        return _search_cache[cache_key][:limit]

    try:
        url = SEARCH_URL.format(keyword=keyword)
        resp = requests.get(url, headers=HEADERS, timeout=5)
        text = resp.text

        # 解析返回格式: v_hint="sh~600519~贵州茅台~gzmt~GP-A^sz~000858~五粮液~wly~GP-A"
        results = []
        if '="' in text:
            data_str = text.split('="', 1)[1].rstrip('";\n')
            items = data_str.split('^')
            for item in items:
                fields = item.split('~')
                if len(fields) >= 3:
                    market = fields[0]
                    code = fields[1]
                    name = fields[2]
                    # 腾讯接口可能返回 \uXXXX 格式的Unicode转义，需要解码
                    if '\\u' in name:
                        try:
                            name = name.encode('utf-8').decode('unicode_escape')
                        except Exception:
                            pass
                    pinyin = fields[3] if len(fields) > 3 else ""
                    # 只保留 A 股（沪市/深市）
                    if market in ("sh", "sz") and code.isdigit() and len(code) == 6:
                        results.append({
                            "symbol": market + code,
                            "name": name,
                            "code": code,
                            "pinyin": pinyin,
                            "market": market,
                        })

        # 缓存结果
        _search_cache[cache_key] = results
        return results[:limit]
    except Exception as e:
        print(f"股票搜索失败: {e}")
        return []
