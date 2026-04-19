"""
量化因子股票操作建议系统
基于技术指标（MA/MACD/RSI/KDJ/布林带/成交量）+ 消息面分析
提供短线/中线/长线操作建议
"""

import gc
import os
import json
import time
import traceback
from datetime import datetime, timedelta
from functools import lru_cache

# SSL 证书修复（解决海外环境证书验证失败）
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

import numpy as np
import pandas as pd
from flask import Flask, render_template, jsonify, request

app = Flask(__name__)

# ============================================================
# akshare 调用重试封装
# ============================================================

def _ak_call(fn, *args, retries=3, delay=2, **kwargs):
    """带重试 + 指数退避的 akshare 调用"""
    last_err = None
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if attempt < retries - 1:
                wait = delay * (1.5 ** attempt)
                print(f"[akshare] 第{attempt+1}次调用失败({e.__class__.__name__}), "
                      f"{wait:.0f}秒后重试...")
                time.sleep(wait)
    raise last_err

# ============================================================
# 全局缓存 + 本地持久化
# ============================================================
_stock_list_cache = {"data": None, "ts": 0}
_STOCK_LIST_TTL = 3600  # 股票列表缓存1小时
_STOCK_LIST_FILE = os.path.join(os.path.dirname(__file__), "stock_list_cache.json")


def _add_pinyin(result):
    """给股票列表加上拼音字段"""
    from pypinyin import lazy_pinyin
    for s in result:
        py = lazy_pinyin(s["name"])
        s["py"] = "".join(py).lower()
        s["py_short"] = "".join(p[0] for p in py).lower()


def _build_stock_list():
    """拉取全A股列表：优先东财(akshare) → 备用新浪"""
    errors = []

    # 数据源1: akshare (东财)
    try:
        import akshare as ak
        df = _ak_call(ak.stock_zh_a_spot_em)
        result = []
        for _, row in df.iterrows():
            code = str(row.get("代码", ""))
            name = str(row.get("名称", ""))
            if code and name:
                result.append({"code": code, "name": name})
        if result:
            _add_pinyin(result)
            print(f"[数据] 东财获取 {len(result)} 只")
            return result
    except Exception as e:
        errors.append(f"东财: {e}")
        print(f"[数据] 东财失败: {e}")

    # 数据源2: 新浪财经（分页拉取）
    try:
        import requests as req
        url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120"}
        all_stocks = []
        page = 1
        while True:
            params = {"page": page, "num": 80, "sort": "symbol", "asc": 1, "node": "hs_a"}
            resp = req.get(url, params=params, headers=headers, timeout=15)
            data = json.loads(resp.text)
            if not data:
                break
            for s in data:
                all_stocks.append({"code": s.get("code", ""), "name": s.get("name", "")})
            if len(data) < 80:
                break
            page += 1
            time.sleep(0.2)
        if all_stocks:
            _add_pinyin(all_stocks)
            print(f"[数据] 新浪获取 {len(all_stocks)} 只")
            return all_stocks
    except Exception as e:
        errors.append(f"新浪: {e}")
        print(f"[数据] 新浪失败: {e}")

    raise Exception("股票列表数据源均不可用: " + "; ".join(errors))


def _save_stock_list_local(data):
    """将股票列表保存到本地 JSON 文件"""
    try:
        with open(_STOCK_LIST_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        print(f"[持久化] 股票列表已保存到本地 ({len(data)} 只)")
    except Exception as e:
        print(f"[持久化] 保存失败: {e}")


def _load_stock_list_local():
    """从本地 JSON 文件加载股票列表"""
    try:
        if os.path.exists(_STOCK_LIST_FILE):
            with open(_STOCK_LIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data:
                print(f"[持久化] 从本地加载股票列表 ({len(data)} 只)")
                return data
    except Exception as e:
        print(f"[持久化] 本地文件读取失败: {e}")
    return None


def _get_stock_name(code):
    """轻量级获取股票名称（仅查缓存/本地文件，不触发API）"""
    # 先从内存缓存找
    stocks = _stock_list_cache.get("data")
    if stocks:
        for s in stocks:
            if s["code"] == code:
                return s["name"]
    # 再从本地文件找
    local_stocks = _load_stock_list_local()
    if local_stocks:
        for s in local_stocks:
            if s["code"] == code:
                return s["name"]
    return code


def get_stock_list(force_refresh=False):
    """获取A股全部股票列表（内存缓存 → API → 本地文件，三级兜底）"""
    now = time.time()

    # 1. 内存缓存有效则直接用
    if not force_refresh and _stock_list_cache["data"] is not None \
            and now - _stock_list_cache["ts"] < _STOCK_LIST_TTL:
        return _stock_list_cache["data"]

    # 2. 尝试从 API 拉取
    try:
        result = _build_stock_list()
        _stock_list_cache["data"] = result
        _stock_list_cache["ts"] = now
        # 同时保存到本地
        _save_stock_list_local(result)
        print(f"[缓存] 股票列表已更新，共 {len(result)} 只")
        return result
    except Exception as e:
        print(f"[缓存] API 获取失败: {e}")

    # 3. API 失败，尝试本地文件
    local_data = _load_stock_list_local()
    if local_data:
        _stock_list_cache["data"] = local_data
        # 不更新 ts，让下次请求继续尝试 API
        return local_data

    # 4. 都失败，返回内存中的旧数据（可能为空）
    print("[缓存] 所有数据源均不可用")
    return _stock_list_cache["data"] or []


# ============================================================
# 技术指标计算（纯 Python，不依赖 TA-Lib）
# ============================================================

def calc_ma(series, period):
    return series.rolling(window=period, min_periods=period).mean()


def calc_ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def calc_macd(close, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(close, fast)
    ema_slow = calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_bar = (dif - dea) * 2
    return dif, dea, macd_bar


def calc_rsi(close, period=6):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    lowest_low = low.rolling(window=n, min_periods=n).min()
    highest_high = high.rolling(window=n, min_periods=n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


def calc_boll(close, period=20, num_std=2):
    mid = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def safe_val(val, default=0.0):
    """安全取值，处理 NaN"""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return float(val)


# ============================================================
# 量化分析引擎
# ============================================================

class StockAnalyzer:
    """股票量化分析器"""

    def __init__(self, df):
        """
        df 需包含列: date, open, close, high, low, volume
        """
        self.df = df.copy()
        self.df = self.df.reset_index(drop=True)
        self._calc_indicators()

    def _calc_indicators(self):
        c = self.df["close"]
        h = self.df["high"]
        l = self.df["low"]
        v = self.df["volume"]

        for p in [5, 10, 20, 60, 120]:
            self.df[f"MA{p}"] = calc_ma(c, p)

        self.df["DIF"], self.df["DEA"], self.df["MACD_bar"] = calc_macd(c)
        self.df["RSI6"] = calc_rsi(c, 6)
        self.df["RSI12"] = calc_rsi(c, 12)
        self.df["RSI24"] = calc_rsi(c, 24)
        self.df["K"], self.df["D_val"], self.df["J"] = calc_kdj(h, l, c)
        self.df["BOLL_upper"], self.df["BOLL_mid"], self.df["BOLL_lower"] = calc_boll(c)

        self.df["VOL_MA5"] = calc_ma(v, 5)
        self.df["VOL_MA10"] = calc_ma(v, 10)

        # 涨跌幅
        self.df["pct_change"] = c.pct_change() * 100

    def _last(self, col, n=1):
        """取倒数第n个有效值"""
        vals = self.df[col].dropna()
        if len(vals) < n:
            return None
        return float(vals.iloc[-n])

    def _prev(self, col, n=2):
        """取倒数第n个有效值"""
        vals = self.df[col].dropna()
        if len(vals) < n:
            return None
        return float(vals.iloc[-n])

    # ----------------------------------------------------------
    # 短线分析 (1-5天): MA5/MA10, KDJ, RSI6, 成交量异动
    # ----------------------------------------------------------
    def analyze_short(self):
        signals = []
        score = 0.0
        last = self.df.iloc[-1]
        prev = self.df.iloc[-2] if len(self.df) >= 2 else last

        # --- MA5 / MA10 金叉/死叉 ---
        ma5 = self._last("MA5")
        ma10 = self._last("MA10")
        p_ma5 = self._prev("MA5", 2)
        p_ma10 = self._prev("MA10", 2)
        if ma5 and ma10 and p_ma5 and p_ma10:
            if p_ma5 <= p_ma10 and ma5 > ma10:
                signals.append({"name": "MA5/MA10金叉", "action": "buy", "score": 1.0,
                                "desc": "短期均线金叉，多头信号"})
                score += 1.0
            elif p_ma5 >= p_ma10 and ma5 < ma10:
                signals.append({"name": "MA5/MA10死叉", "action": "sell", "score": -1.0,
                                "desc": "短期均线死叉，空头信号"})
                score -= 1.0
            elif ma5 > ma10:
                signals.append({"name": "MA5>MA10", "action": "buy", "score": 0.3,
                                "desc": "短期均线多头排列"})
                score += 0.3
            else:
                signals.append({"name": "MA5<MA10", "action": "sell", "score": -0.3,
                                "desc": "短期均线空头排列"})
                score -= 0.3

        # --- KDJ ---
        k = self._last("K")
        d = self._last("D_val")
        j = self._last("J")
        pk = self._prev("K", 2)
        pd_ = self._prev("D_val", 2)
        if k is not None and d is not None:
            if k > 80:
                sig = {"name": f"KDJ超买(K={k:.1f})", "action": "sell", "score": -0.5,
                       "desc": "K值进入超买区，短线回调风险加大"}
                signals.append(sig)
                score -= 0.5
            elif k < 20:
                sig = {"name": f"KDJ超卖(K={k:.1f})", "action": "buy", "score": 0.5,
                       "desc": "K值进入超卖区，短线反弹概率增大"}
                signals.append(sig)
                score += 0.5
            if pk is not None and pd_ is not None:
                if pk <= pd_ and k > d:
                    signals.append({"name": "KDJ金叉", "action": "buy", "score": 1.0,
                                    "desc": "KDJ指标金叉，短线买入信号"})
                    score += 1.0
                elif pk >= pd_ and k < d:
                    signals.append({"name": "KDJ死叉", "action": "sell", "score": -1.0,
                                    "desc": "KDJ指标死叉，短线卖出信号"})
                    score -= 1.0

        # --- RSI6 ---
        rsi6 = self._last("RSI6")
        if rsi6 is not None:
            if rsi6 > 80:
                signals.append({"name": f"RSI超买({rsi6:.1f})", "action": "sell", "score": -1.0,
                                "desc": "RSI进入超买区，短线过热"})
                score -= 1.0
            elif rsi6 < 20:
                signals.append({"name": f"RSI超卖({rsi6:.1f})", "action": "buy", "score": 1.0,
                                "desc": "RSI进入超卖区，短线超跌反弹可期"})
                score += 1.0
            elif rsi6 > 60:
                signals.append({"name": f"RSI偏强({rsi6:.1f})", "action": "buy", "score": 0.3,
                                "desc": "RSI处于强势区间"})
                score += 0.3
            elif rsi6 < 40:
                signals.append({"name": f"RSI偏弱({rsi6:.1f})", "action": "sell", "score": -0.3,
                                "desc": "RSI处于弱势区间"})
                score -= 0.3

        # --- 成交量异动 ---
        vol_ma5 = self._last("VOL_MA5")
        vol = self._last("volume") if "volume" in self.df.columns else None
        if vol_ma5 and vol and vol_ma5 > 0:
            vol_ratio = vol / vol_ma5
            if vol_ratio > 2.0:
                price_up = self._last("close") > self._prev("close", 2)
                if price_up:
                    signals.append({"name": f"放量上涨(量比{vol_ratio:.1f})", "action": "buy",
                                    "score": 0.8, "desc": "成交量显著放大且价格上涨，多头力量强劲"})
                    score += 0.8
                else:
                    signals.append({"name": f"放量下跌(量比{vol_ratio:.1f})", "action": "sell",
                                    "score": -0.8, "desc": "成交量显著放大但价格下跌，抛压沉重"})
                    score -= 0.8
            elif vol_ratio < 0.5:
                signals.append({"name": f"缩量整理(量比{vol_ratio:.1f})", "action": "hold",
                                "score": 0.0, "desc": "成交量萎缩，市场观望情绪浓厚"})

        # --- 价格位置 vs MA5 ---
        close_price = self._last("close")
        if ma5 and close_price:
            pct = (close_price - ma5) / ma5 * 100
            if pct > 3:
                signals.append({"name": f"偏离MA5过远(+{pct:.1f}%)", "action": "sell",
                                "score": -0.5, "desc": "短期偏离均线过远，有回归需求"})
                score -= 0.5
            elif pct < -3:
                signals.append({"name": f"跌破MA5({pct:.1f}%)", "action": "sell",
                                "score": -0.5, "desc": "收盘跌破5日均线，短线走弱"})
                score -= 0.5

        return score, signals

    # ----------------------------------------------------------
    # 中线分析 (1-3月): MA20/MA60, MACD, 布林带, 趋势
    # ----------------------------------------------------------
    def analyze_medium(self):
        signals = []
        score = 0.0

        # --- MA20 / MA60 ---
        ma20 = self._last("MA20")
        ma60 = self._last("MA60")
        p_ma20 = self._prev("MA20", 2)
        p_ma60 = self._prev("MA60", 2)
        if ma20 and ma60 and p_ma20 and p_ma60:
            if p_ma20 <= p_ma60 and ma20 > ma60:
                signals.append({"name": "MA20/MA60金叉", "action": "buy", "score": 1.5,
                                "desc": "中期均线金叉，趋势转多"})
                score += 1.5
            elif p_ma20 >= p_ma60 and ma20 < ma60:
                signals.append({"name": "MA20/MA60死叉", "action": "sell", "score": -1.5,
                                "desc": "中期均线死叉，趋势转空"})
                score -= 1.5
            elif ma20 > ma60:
                signals.append({"name": "MA20>MA60多头", "action": "buy", "score": 0.5,
                                "desc": "中期均线多头排列"})
                score += 0.5
            else:
                signals.append({"name": "MA20<MA60空头", "action": "sell", "score": -0.5,
                                "desc": "中期均线空头排列"})
                score -= 0.5

        # --- MACD ---
        dif = self._last("DIF")
        dea = self._last("DEA")
        macd_bar = self._last("MACD_bar")
        p_dif = self._prev("DIF", 2)
        p_dea = self._prev("DEA", 2)
        if dif is not None and dea is not None and p_dif is not None and p_dea is not None:
            if p_dif <= p_dea and dif > dea:
                signals.append({"name": "MACD金叉", "action": "buy", "score": 1.5,
                                "desc": "MACD金叉，中期趋势转强"})
                score += 1.5
            elif p_dif >= p_dea and dif < dea:
                signals.append({"name": "MACD死叉", "action": "sell", "score": -1.5,
                                "desc": "MACD死叉，中期趋势转弱"})
                score -= 1.5
            elif dif > dea:
                signals.append({"name": "MACD多头运行", "action": "buy", "score": 0.5,
                                "desc": "DIF位于DEA之上，中期动能偏多"})
                score += 0.5
            else:
                signals.append({"name": "MACD空头运行", "action": "sell", "score": -0.5,
                                "desc": "DIF位于DEA之下，中期动能偏空"})
                score -= 0.5

            # MACD柱趋势
            if macd_bar is not None:
                if macd_bar > 0:
                    signals.append({"name": "MACD红柱", "action": "buy", "score": 0.3,
                                    "desc": "MACD柱为正，多头动能"})
                    score += 0.3
                else:
                    signals.append({"name": "MACD绿柱", "action": "sell", "score": -0.3,
                                    "desc": "MACD柱为负，空头动能"})
                    score -= 0.3

        # --- 布林带 ---
        boll_upper = self._last("BOLL_upper")
        boll_mid = self._last("BOLL_mid")
        boll_lower = self._last("BOLL_lower")
        close_price = self._last("close")
        if all(v is not None for v in [boll_upper, boll_mid, boll_lower, close_price]):
            if boll_upper != boll_lower:
                pct_b = (close_price - boll_lower) / (boll_upper - boll_lower)
                if pct_b > 0.9:
                    signals.append({"name": f"触及布林上轨(%B={pct_b:.2f})", "action": "sell",
                                    "score": -0.8, "desc": "价格接近布林上轨，注意回调风险"})
                    score -= 0.8
                elif pct_b < 0.1:
                    signals.append({"name": f"触及布林下轨(%B={pct_b:.2f})", "action": "buy",
                                    "score": 0.8, "desc": "价格接近布林下轨，可能出现反弹"})
                    score += 0.8
                elif pct_b > 0.6:
                    signals.append({"name": f"布林带偏强(%B={pct_b:.2f})", "action": "buy",
                                    "score": 0.3, "desc": "价格在布林带中上区间运行"})
                    score += 0.3
                elif pct_b < 0.4:
                    signals.append({"name": f"布林带偏弱(%B={pct_b:.2f})", "action": "sell",
                                    "score": -0.3, "desc": "价格在布林带中下区间运行"})
                    score -= 0.3

        # --- 近20日涨跌幅 ---
        if len(self.df) >= 20:
            ret_20 = (self.df["close"].iloc[-1] / self.df["close"].iloc[-20] - 1) * 100
            if ret_20 > 15:
                signals.append({"name": f"20日涨幅{ret_20:.1f}%", "action": "sell",
                                "score": -0.5, "desc": "中期涨幅较大，注意获利回吐"})
                score -= 0.5
            elif ret_20 < -15:
                signals.append({"name": f"20日跌幅{ret_20:.1f}%", "action": "buy",
                                "score": 0.5, "desc": "中期跌幅较大，可能有技术反弹"})
                score += 0.5

        return score, signals

    # ----------------------------------------------------------
    # 长线分析 (3月+): 长期趋势, 均线系统, 基本面指标
    # ----------------------------------------------------------
    def analyze_long(self):
        signals = []
        score = 0.0

        close_price = self._last("close")

        # --- MA60 / MA120 趋势 ---
        ma60 = self._last("MA60")
        ma120 = self._last("MA120")
        p_ma60 = self._prev("MA60", 2)
        p_ma120 = self._prev("MA120", 2)
        if ma60 and ma120 and p_ma60 and p_ma120:
            if p_ma60 <= p_ma120 and ma60 > ma120:
                signals.append({"name": "MA60/MA120金叉", "action": "buy", "score": 2.0,
                                "desc": "长期均线金叉，大趋势转多"})
                score += 2.0
            elif p_ma60 >= p_ma120 and ma60 < ma120:
                signals.append({"name": "MA60/MA120死叉", "action": "sell", "score": -2.0,
                                "desc": "长期均线死叉，大趋势转空"})
                score -= 2.0
            elif ma60 > ma120:
                signals.append({"name": "长期均线多头", "action": "buy", "score": 0.8,
                                "desc": "长期均线多头排列，趋势向上"})
                score += 0.8
            else:
                signals.append({"name": "长期均线空头", "action": "sell", "score": -0.8,
                                "desc": "长期均线空头排列，趋势向下"})
                score -= 0.8

        # --- 价格 vs MA120 ---
        if ma120 and close_price:
            pct = (close_price - ma120) / ma120 * 100
            if pct > 30:
                signals.append({"name": f"远高于半年线(+{pct:.1f}%)", "action": "sell",
                                "score": -0.8, "desc": "价格远超长期均线，估值偏高"})
                score -= 0.8
            elif pct < -20:
                signals.append({"name": f"远低于半年线({pct:.1f}%)", "action": "buy",
                                "score": 0.8, "desc": "价格远低于长期均线，可能被低估"})
                score += 0.8

        # --- MA60 斜率 ---
        if len(self.df) >= 10:
            ma60_vals = self.df["MA60"].dropna()
            if len(ma60_vals) >= 10:
                slope = (ma60_vals.iloc[-1] - ma60_vals.iloc[-10]) / ma60_vals.iloc[-10] * 100
                if slope > 2:
                    signals.append({"name": f"MA60斜率上行({slope:.1f}%)", "action": "buy",
                                    "score": 0.5, "desc": "60日均线持续上行，长期趋势向好"})
                    score += 0.5
                elif slope < -2:
                    signals.append({"name": f"MA60斜率下行({slope:.1f}%)", "action": "sell",
                                    "score": -0.5, "desc": "60日均线持续下行，长期趋势向弱"})
                    score -= 0.5

        # --- 近60日涨跌幅 ---
        if len(self.df) >= 60:
            ret_60 = (self.df["close"].iloc[-1] / self.df["close"].iloc[-60] - 1) * 100
            if ret_60 > 30:
                signals.append({"name": f"60日涨幅{ret_60:.1f}%", "action": "sell",
                                "score": -0.5, "desc": "中长期涨幅显著，需警惕高位风险"})
                score -= 0.5
            elif ret_60 < -30:
                signals.append({"name": f"60日跌幅{ret_60:.1f}%", "action": "buy",
                                "score": 0.5, "desc": "中长期跌幅较深，具备长期配置价值"})
                score += 0.5

        # --- MACD 零轴 ---
        dif = self._last("DIF")
        if dif is not None:
            if dif > 0:
                signals.append({"name": "DIF位于零轴上方", "action": "buy", "score": 0.5,
                                "desc": "MACD零轴之上运行，中长期趋势偏多"})
                score += 0.5
            else:
                signals.append({"name": "DIF位于零轴下方", "action": "sell", "score": -0.5,
                                "desc": "MACD零轴之下运行，中长期趋势偏空"})
                score -= 0.5

        return score, signals

    # ----------------------------------------------------------
    # 综合分析
    # ----------------------------------------------------------
    def get_recommendation(self, strategy="short"):
        if strategy == "short":
            score, signals = self.analyze_short()
        elif strategy == "medium":
            score, signals = self.analyze_medium()
        else:
            score, signals = self.analyze_long()

        # 归一化评分到 [-5, 5]
        max_score = sum(abs(s["score"]) for s in signals) if signals else 1
        normalized = score / max_score * 5 if max_score > 0 else 0

        # 映射建议
        if normalized > 3:
            rec = "强烈买入"
            strength = "极强"
        elif normalized > 1.5:
            rec = "建议买入"
            strength = "强"
        elif normalized > 0.5:
            rec = "谨慎买入"
            strength = "中等"
        elif normalized > -0.5:
            rec = "观望持有"
            strength = "弱"
        elif normalized > -1.5:
            rec = "谨慎卖出"
            strength = "中等"
        elif normalized > -3:
            rec = "建议卖出"
            strength = "强"
        else:
            rec = "强烈卖出"
            strength = "极强"

        # 关键价位
        levels = self._calc_key_levels(strategy)

        return {
            "recommendation": rec,
            "strength": strength,
            "score": round(normalized, 2),
            "raw_score": round(score, 2),
            "signals": signals,
            "key_levels": levels,
            "strategy": strategy
        }

    def _calc_key_levels(self, strategy):
        close = self._last("close")
        high = self._last("high")
        low = self._last("low")

        # 近期高低点
        if strategy == "short":
            window = 10
        elif strategy == "medium":
            window = 30
        else:
            window = 60

        window = min(window, len(self.df))
        recent = self.df.tail(window)
        resistance = float(recent["high"].max())
        support = float(recent["low"].min())

        # 止损/止盈建议
        if strategy == "short":
            stop_loss = close * 0.95
            target = close * 1.05
        elif strategy == "medium":
            stop_loss = close * 0.90
            target = close * 1.15
        else:
            stop_loss = close * 0.85
            target = close * 1.30

        return {
            "current": round(close, 2),
            "support": round(support, 2),
            "resistance": round(resistance, 2),
            "stop_loss": round(stop_loss, 2),
            "target": round(target, 2)
        }

    def get_chart_data(self):
        """返回图表所需数据"""
        result = []
        for _, row in self.df.iterrows():
            item = {
                "date": row["date"] if isinstance(row["date"], str) else str(row["date"])[:10],
                "open": safe_val(row["open"]),
                "close": safe_val(row["close"]),
                "high": safe_val(row["high"]),
                "low": safe_val(row["low"]),
                "volume": safe_val(row["volume"]),
            }
            # 均线
            for p in [5, 10, 20, 60]:
                item[f"MA{p}"] = safe_val(row.get(f"MA{p}"), None)
            # MACD
            item["DIF"] = safe_val(row.get("DIF"), None)
            item["DEA"] = safe_val(row.get("DEA"), None)
            item["MACD_bar"] = safe_val(row.get("MACD_bar"), None)
            # KDJ
            item["K"] = safe_val(row.get("K"), None)
            item["D_val"] = safe_val(row.get("D_val"), None)
            item["J"] = safe_val(row.get("J"), None)
            result.append(item)
        return result


# ============================================================
# 消息面分析
# ============================================================

def analyze_news_sentiment(code, stock_name):
    """
    基于新闻和基本面数据给出消息面评估（内存优化版）
    使用单股查询代替全市场行情，避免 OOM
    """
    points = []
    score = 0.0

    # --- 基本面数据：百度估值（全球CDN，海外可访问） ---
    try:
        import akshare as ak
        pe_df = _ak_call(
            ak.stock_zh_valuation_baidu,
            symbol=code, indicator="市盈率(TTM)", period="近一年",
            retries=1, delay=2
        )
        if pe_df is not None and not pe_df.empty:
            pe = safe_val(pe_df.iloc[-1]["value"], None)
            if pe is not None and pe > 0:
                if pe < 15:
                    points.append({"text": f"市盈率(TTM){pe:.1f}倍，估值偏低", "bias": "positive"})
                    score += 0.5
                elif pe < 30:
                    points.append({"text": f"市盈率(TTM){pe:.1f}倍，估值适中", "bias": "neutral"})
                elif pe < 60:
                    points.append({"text": f"市盈率(TTM){pe:.1f}倍，估值偏高", "bias": "negative"})
                    score -= 0.3
                else:
                    points.append({"text": f"市盈率(TTM){pe:.1f}倍，估值过高", "bias": "negative"})
                    score -= 0.5
        del pe_df
    except Exception as e:
        print(f"[消息面] PE获取失败: {e}")

    try:
        import akshare as ak
        mv_df = _ak_call(
            ak.stock_zh_valuation_baidu,
            symbol=code, indicator="总市值", period="近一年",
            retries=1, delay=2
        )
        if mv_df is not None and not mv_df.empty:
            mv = safe_val(mv_df.iloc[-1]["value"], None)
            if mv and mv > 0:
                if mv > 1000:
                    points.append({"text": f"总市值{mv:.0f}亿，大盘蓝筹", "bias": "neutral"})
                elif mv > 200:
                    points.append({"text": f"总市值{mv:.0f}亿，中盘股", "bias": "neutral"})
                else:
                    points.append({"text": f"总市值{mv:.0f}亿，小盘股", "bias": "neutral"})
        del mv_df
    except Exception as e:
        print(f"[消息面] 市值获取失败: {e}")

    gc.collect()

    # --- 个股新闻（轻量，仅取5条） ---
    try:
        import akshare as ak
        news_df = _ak_call(ak.stock_news_em, symbol=code, retries=1, delay=2)
        if news_df is not None and not news_df.empty:
            for _, nr in news_df.head(5).iterrows():
                title = str(nr.get("新闻标题", ""))
                if not title:
                    continue
                bias = "neutral"
                if any(kw in title for kw in ["上涨", "涨停", "新高", "突破", "增长", "利好", "获批", "中标"]):
                    bias = "positive"
                    score += 0.2
                elif any(kw in title for kw in ["下跌", "跌停", "新低", "亏损", "减持", "处罚", "风险", "利空"]):
                    bias = "negative"
                    score -= 0.2
                points.append({"text": f"[新闻] {title[:40]}", "bias": bias, "is_news": True})
        del news_df
    except Exception as e:
        print(f"[消息面] 新闻获取失败: {e}")

    gc.collect()

    return {
        "score": round(score, 2),
        "points": points
    }


# ============================================================
# 数据获取（多数据源兜底）
# ============================================================

def _code_to_sina_symbol(code):
    """股票代码转为新浪格式: sz002478 / sh600519"""
    if code.startswith(("6", "9")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_via_sina(code, datalen=800):
    """通过新浪财经获取K线数据（备用源，最多支持800条日线）"""
    import requests as req

    symbol = _code_to_sina_symbol(code)
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {
        "symbol": symbol,
        "scale": "240",   # 日线
        "ma": "no",
        "datalen": str(datalen),
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.sina.com.cn/",
    }

    for attempt in range(1):
        try:
            resp = req.get(url, params=params, headers=headers, timeout=8)
            resp.raise_for_status()
            break
        except Exception as e:
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
            else:
                raise

    import json as _json
    raw = _json.loads(resp.text)
    if not raw:
        raise Exception(f"新浪接口返回空数据 ({code})")

    rows = []
    for item in raw:
        rows.append({
            "date": item["day"],
            "open": float(item["open"]),
            "close": float(item["close"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "volume": float(item["volume"]),
        })
    return pd.DataFrame(rows)


def _fetch_via_yahoo(code, days=365):
    """通过 Yahoo Finance Chart API 获取K线数据"""
    import requests as req

    # 转换代码格式：600519 → 600519.SS，002384 → 002384.SZ
    if code.startswith(("6", "9")):
        ticker = f"{code}.SS"
    elif code.startswith("8") or code.startswith("4"):
        ticker = f"{code}.BJ"
    else:
        ticker = f"{code}.SZ"

    # 将天数转换为 Yahoo range 参数
    if days >= 3650:
        yrange = "10y"
    elif days >= 1825:
        yrange = "5y"
    elif days >= 730:
        yrange = "2y"
    elif days >= 365:
        yrange = "1y"
    elif days >= 180:
        yrange = "6mo"
    elif days >= 90:
        yrange = "3mo"
    else:
        yrange = "1mo"

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    params = {"range": yrange, "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120"}

    resp = req.get(url, params=params, headers=headers, timeout=8)
    resp.raise_for_status()
    data = resp.json()

    result = data.get("chart", {}).get("result", [])
    if not result:
        raise Exception(f"Yahoo Finance 返回空数据 ({ticker})")

    timestamps = result[0].get("timestamp", [])
    quote = result[0].get("indicators", {}).get("quote", [{}])[0]

    rows = []
    for i, ts in enumerate(timestamps):
        try:
            d = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            close_val = quote["close"][i]
            if close_val is None:
                continue
            rows.append({
                "date": d,
                "open": float(quote["open"][i] or 0),
                "close": float(close_val),
                "high": float(quote["high"][i] or 0),
                "low": float(quote["low"][i] or 0),
                "volume": float(quote["volume"][i] or 0),
            })
        except (TypeError, ValueError, IndexError):
            continue

    return pd.DataFrame(rows)


def _fetch_via_twelvedata(code, days=365):
    """通过 Twelve Data API 获取K线数据（全球CDN，海外首选，免费800次/天）"""
    import requests as req

    apikey = os.environ.get("TWELVEDATA_API_KEY", "demo")
    if apikey == "demo":
        raise Exception("未配置 Twelve Data API key")

    # 确定交易所
    if code.startswith(("6", "9")):
        exchange = "SSE"   # 上交所
    elif code.startswith("8") or code.startswith("4"):
        exchange = "BSE"   # 北交所
    else:
        exchange = "SZSE"  # 深交所

    outputsize = min(days, 5000)

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": code,
        "exchange": exchange,
        "interval": "1day",
        "outputsize": outputsize,
        "format": "JSON",
        "apikey": apikey,
    }

    resp = req.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise Exception(f"Twelve Data: {data.get('message', '未知错误')}")

    values = data.get("values", [])
    if not values:
        raise Exception(f"Twelve Data 返回空数据 ({code})")

    rows = []
    for v in values:
        try:
            rows.append({
                "date": v["datetime"][:10],
                "open": float(v["open"]),
                "close": float(v["close"]),
                "high": float(v["high"]),
                "low": float(v["low"]),
                "volume": float(v.get("volume") or 0),
            })
        except (TypeError, ValueError, KeyError):
            continue

    # Twelve Data 返回最新的在前，需反转
    rows.reverse()
    return pd.DataFrame(rows)


def _fetch_via_akshare(code, days=365):
    """通过 akshare (东财) 获取K线数据"""
    import akshare as ak

    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

    df = _ak_call(
        ak.stock_zh_a_hist,
        symbol=code, period="daily",
        start_date=start_date, end_date=end_date, adjust="qfq",
        retries=1,
    )

    col_map = {
        "日期": "date", "开盘": "open", "收盘": "close",
        "最高": "high", "最低": "low", "成交量": "volume",
        "成交额": "amount", "涨跌幅": "change_pct",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    for col in ["open", "close", "high", "low", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["close"])
    return df


def fetch_stock_data(code, days=3650):
    """获取股票历史数据 — TwelveData → Yahoo → 新浪，顺序获取，硬性25秒截止"""
    _start = time.time()
    _deadline = 25
    errors = []

    # 1. Twelve Data（全球CDN，海外最快）
    if time.time() - _start < _deadline:
        try:
            df = _fetch_via_twelvedata(code, days)
            if not df.empty:
                print(f"[数据] {code} 从TwelveData获取 {len(df)} 条 ({time.time()-_start:.1f}s)")
                return df
        except Exception as e:
            errors.append(f"TwelveData: {e}")
            print(f"[数据] TwelveData失败 ({time.time()-_start:.1f}s): {e}")

    # 2. Yahoo Finance（全球CDN）
    if time.time() - _start < _deadline:
        try:
            df = _fetch_via_yahoo(code, days)
            if not df.empty:
                print(f"[数据] {code} 从Yahoo获取 {len(df)} 条 ({time.time()-_start:.1f}s)")
                return df
        except Exception as e:
            errors.append(f"Yahoo: {e}")
            print(f"[数据] Yahoo失败 ({time.time()-_start:.1f}s): {e}")

    # 3. 新浪财经（国内源，海外可能不通）
    if time.time() - _start < _deadline:
        try:
            df = _fetch_via_sina(code, min(days, 800))
            if not df.empty:
                print(f"[数据] {code} 从新浪获取 {len(df)} 条 ({time.time()-_start:.1f}s)")
                return df
        except Exception as e:
            errors.append(f"新浪: {e}")
            print(f"[数据] 新浪失败 ({time.time()-_start:.1f}s): {e}")

    raise Exception("所有数据源均不可用: " + "; ".join(errors))


# ============================================================
# Flask 路由
# ============================================================

@app.route("/")
def index():
    return render_template("index.html", v=int(time.time()))


@app.route("/api/health")
def health_check():
    """健康检查接口"""
    return jsonify({
        "status": "ok",
        "version": "sequential-v4",
        "twelvedata": "configured" if os.environ.get("TWELVEDATA_API_KEY") else "not_set",
        "time": datetime.now().isoformat(),
    })


@app.route("/api/debug/sources/<code>")
def debug_sources(code):
    """调试接口：逐个测试每个数据源，返回结果（不超时）"""
    results = {}

    def _test(name, fn, *args):
        t = time.time()
        try:
            df = fn(*args)
            return {"status": "ok", "rows": len(df), "time": f"{time.time()-t:.1f}s"}
        except Exception as e:
            return {"status": "fail", "error": str(e)[:100], "time": f"{time.time()-t:.1f}s"}

    results["twelvedata"] = _test("twelvedata", _fetch_via_twelvedata, code, 365)
    results["yahoo"] = _test("yahoo", _fetch_via_yahoo, code, 365)
    results["sina"] = _test("sina", _fetch_via_sina, code, 800)

    return jsonify(results)


@app.route("/api/search")
def search_stock():
    """搜索股票 — 优先用缓存，秒级响应"""
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify([])
    # 搜索接口优先用内存/本地缓存，不触发 API 重试（保证响应速度）
    stocks = _stock_list_cache.get("data")
    if not stocks:
        stocks = _load_stock_list_local()
    if not stocks:
        # 最后兜底才尝试 API，但只试一次
        try:
            stocks = _build_stock_list()
            _stock_list_cache["data"] = stocks
            _stock_list_cache["ts"] = time.time()
            _save_stock_list_local(stocks)
        except Exception:
            stocks = []
    if not stocks:
        return jsonify([])

    q_lower = q.lower()
    results = []
    exact = []       # 精确匹配（代码或名称完全一致）
    code_match = []  # 代码前缀匹配
    name_match = []  # 名称包含匹配
    py_match = []    # 拼音匹配

    for s in stocks:
        code = s.get("code", "")
        name = s.get("name", "")
        py = s.get("py", "")
        py_short = s.get("py_short", "")

        # 精确匹配
        if code == q_lower or name == q:
            exact.append(s)
            continue
        # 代码前缀
        if code.startswith(q_lower):
            code_match.append(s)
            continue
        # 名称包含
        if q in name:
            name_match.append(s)
            continue
        # 拼音首字母前缀（如 "zdg" → 中电港）
        if py_short.startswith(q_lower):
            py_match.append(s)
            continue
        # 全拼包含（如 "zhongdian" → 中电港）
        if py and q_lower in py:
            py_match.append(s)
            continue

    # 按优先级合并，截取前12条
    merged = exact + code_match + name_match + py_match
    for s in merged[:12]:
        results.append({"code": s["code"], "name": s["name"]})
    return jsonify(results)


@app.route("/api/stock/<code>")
def get_stock_analysis(code):
    """获取股票技术分析 + 图表数据（快速，不含消息面）"""
    try:
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            return jsonify({"error": "请输入6位股票代码"}), 400

        # 获取K线数据
        df = fetch_stock_data(code)
        if df.empty:
            return jsonify({"error": "未找到该股票数据"}), 404

        # 获取股票名称（仅查缓存，不触发API拉取5500只股票）
        stock_name = _get_stock_name(code)

        # 技术分析（纯计算，快速）
        analyzer = StockAnalyzer(df)
        del df
        gc.collect()

        short_rec = analyzer.get_recommendation("short")
        medium_rec = analyzer.get_recommendation("medium")
        long_rec = analyzer.get_recommendation("long")

        chart_data = analyzer.get_chart_data()
        del analyzer
        gc.collect()

        return jsonify({
            "code": code,
            "name": stock_name,
            "chart_data": chart_data,
            "recommendations": {
                "short": short_rec,
                "medium": medium_rec,
                "long": long_rec
            }
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"分析失败: {str(e)}"}), 500


@app.route("/api/stock/<code>/news")
def get_stock_news(code):
    """获取股票消息面分析（独立接口，可慢可失败）"""
    try:
        code = code.strip()
        if not code.isdigit() or len(code) != 6:
            return jsonify({"error": "无效代码"}), 400

        stock_name = _get_stock_name(code)

        news_sentiment = analyze_news_sentiment(code, stock_name)
        return jsonify(news_sentiment)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"消息面获取失败: {str(e)}", "score": 0, "points": []}), 200


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("  量化因子股票操作建议系统")
    print("  访问 http://127.0.0.1:5000")
    print("=" * 50)
    # 启动时预热股票列表
    print("[预热] 正在加载股票列表...")
    try:
        stocks = get_stock_list()
        print(f"[预热] 完成，共 {len(stocks)} 只股票")
    except Exception as e:
        print(f"[预热] 失败（将在首次搜索时重试）: {e}")
    app.run(debug=False, host="0.0.0.0", port=5000)
