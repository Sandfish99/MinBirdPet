# -*- coding: utf-8 -*-
"""珉鸟的信息服务 —— DeepSeek 余额 / 今日天气。

设计约束（很重要）：
1. 零第三方依赖。只用标准库 urllib/json，避免 PyInstaller 打包体积膨胀。
2. 所有网络请求都在后台线程跑，主线程（Win32 消息循环）只负责取结果。
   桌宠的动画建立在 30fps 的 WM_TIMER 上，任何阻塞都会让鸟卡住。
3. 结果通过 queue 回传，主线程在 _tick 里 drain，绝不跨线程碰窗口/PIL。

数据源：
- DeepSeek 余额：https://api.deepseek.com/user/balance （官方，Bearer 鉴权）
- 天气：Open-Meteo，免费、无需 API key、支持中文城市名
- 兜底定位：ipwho.is（ipapi.co 在国内会被 403）
"""

from __future__ import annotations

import json
import queue
import random
import threading
import urllib.error
import urllib.parse
import urllib.request

DEEPSEEK_BALANCE_URL = "https://api.deepseek.com/user/balance"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
IP_LOCATE_URL = "https://ipwho.is/"
# pconline 返回中文地名（"山东省"/"济南市"），国内最准；ipwho 是英文但带经纬度
IP_CN_URL = "https://whois.pconline.com.cn/ipJson.jsp?json=true"

UA = "MinBirdPet/1.1 (+desktop pet)"

# WMO weather code -> 中文
WMO_ZH = {
    0: "晴", 1: "晴间少云", 2: "局部多云", 3: "阴",
    45: "雾", 48: "冻雾",
    51: "小毛毛雨", 53: "毛毛雨", 55: "大毛毛雨",
    56: "冻毛毛雨", 57: "强冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "小阵雨", 81: "阵雨", 82: "强阵雨",
    85: "小阵雪", 86: "大阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "强雷阵雨伴冰雹",
}


def wmo_zh(code) -> str:
    try:
        return WMO_ZH.get(int(code), "未知天气")
    except (TypeError, ValueError):
        return "未知天气"


def _get_json(url: str, headers: dict | None = None, timeout: float = 10.0):
    hdr = {"Accept": "application/json", "User-Agent": UA}
    hdr.update(headers or {})
    req = urllib.request.Request(url, headers=hdr, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


# --------------------------------------------------------------------------
# 地理编码 / 定位
# --------------------------------------------------------------------------
ADMIN_SUFFIXES = ("特别行政区", "自治州", "自治区", "地区", "市", "县", "区", "盟", "旗", "省")


def _strip_admin(name: str) -> str:
    """'济南市' -> '济南'。Open-Meteo 的库里存的是不带行政后缀的名字。"""
    for suf in sorted(ADMIN_SUFFIXES, key=len, reverse=True):
        if name.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)].strip()
    return ""


def _geocode_ex(city: str, timeout: float):
    """返回 (geo_result|None, used_query)。used_query 是真正搜中的那个名字。"""
    base = (city or "").strip()
    if not base:
        return None, ""

    def search(name):
        q = urllib.parse.urlencode(
            {"name": name, "count": 5, "language": "zh", "format": "json"})
        data = _get_json(f"{GEOCODE_URL}?{q}", timeout=timeout)
        return data.get("results") or []

    results = []
    used = base
    try:
        results = search(base)
    except Exception:
        results = []
    if not results:
        alt = _strip_admin(base)
        if alt:
            try:
                results = search(alt)
            except Exception:
                results = []
            if results:
                used = alt
    if not results:
        return None, base

    # 同名城市很多（"北京" 能命中北京市 / 重庆 / 四川）。
    # 结果按相关性排，第一条通常是人口最多的那个；
    # 若写的是 "山东济南" 这类带区划的写法，优先挑 admin1 命中省份的。
    top = results[0]
    admin_hint = None
    for suffix in ("省", "市", "自治区"):
        idx = used.find(suffix)
        if idx > 0:
            admin_hint = used[:idx]
            break
    if admin_hint:
        for r in results:
            a1 = r.get("admin1") or ""
            if admin_hint and (admin_hint in a1 or a1 in admin_hint):
                return r, used
    return top, used


def geocode(city: str, timeout: float = 10.0):
    """中文城市名 -> {name, admin1, latitude, longitude, timezone}"""
    g, _used = _geocode_ex(city, timeout)
    return g


def locate_by_ip(timeout: float = 6.0):
    """IP 粗定位。中文地名优先（pconline），拿不到再退回 ipwho 的经纬度。
    返回 {"name": str|None, "latitude": float|None, "longitude": float|None}
    """
    try:
        req = urllib.request.Request(IP_CN_URL, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        text = None
        for enc in ("utf-8", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", "replace")
        data = json.loads(text.strip())
        city = (data.get("city") or "").strip()
        if city and not data.get("err"):
            return {"name": city, "latitude": None, "longitude": None}
    except Exception:
        pass

    try:
        data = _get_json(IP_LOCATE_URL, timeout=timeout)
    except Exception:
        return {"name": None, "latitude": None, "longitude": None}
    if not data.get("success", True):
        return {"name": None, "latitude": None, "longitude": None}
    return {"name": data.get("city"), "latitude": data.get("latitude"),
            "longitude": data.get("longitude")}


def _name_from_geo(g: dict, fallback: str) -> str:
    """把 geocode 结果拼成显示名，避免 '北京市' + '北京' = '北京市北京'。"""
    name = (g.get("name") or fallback or "").strip()
    a1 = (g.get("admin1") or "").strip()
    if not a1:
        return name or fallback
    if name and name in a1:          # "北京" in "北京市" -> 直接用 "北京市"
        return a1
    if name and a1 in name:
        return name
    return f"{a1}{name}" if name else a1


def _resolve_location(city: str | None, timeout: float):
    """返回 (display_name, lat, lon, query_name)。
    query_name 是写回配置、下次能直接搜中的名字（不带行政后缀）。
    城市解析失败时逐级用 IP / 北京兜底。
    """
    if city:
        g, used = _geocode_ex(city, timeout)
        if g and g.get("latitude") is not None:
            return _name_from_geo(g, used), g["latitude"], g["longitude"], used

    ip = locate_by_ip()
    name, lat, lon = ip.get("name"), ip.get("latitude"), ip.get("longitude")
    if lat is not None and lon is not None:
        return (name or "本地"), lat, lon, (name or "")

    if name:
        g, used = _geocode_ex(name, timeout)
        if g and g.get("latitude") is not None:
            return _name_from_geo(g, used), g["latitude"], g["longitude"], used

    g, used = _geocode_ex("北京", timeout)
    if not g:
        raise RuntimeError("定位失败，也拿不到天气")
    return "北京", g["latitude"], g["longitude"], used


# --------------------------------------------------------------------------
# 具体查询
# --------------------------------------------------------------------------
def fetch_weather(city: str | None, timeout: float = 10.0):
    """返回 (text, query_city)。text 为多行情泡文本，query_city 用于写回配置。"""
    resolved, lat, lon, query_city = _resolve_location(city, timeout=timeout)

    q = urllib.parse.urlencode({
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": ("weather_code,temperature_2m_max,temperature_2m_min,"
                  "precipitation_probability_max,uv_index_max"),
        "timezone": "auto",
        "forecast_days": 2,
    })
    data = _get_json(f"{FORECAST_URL}?{q}", timeout=timeout)

    cur = data.get("current") or {}
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    tmax = daily.get("temperature_2m_max") or []
    tmin = daily.get("temperature_2m_min") or []
    pop = daily.get("precipitation_probability_max") or []
    uv = daily.get("uv_index_max") or []
    dcode = daily.get("weather_code") or []

    temp = cur.get("temperature_2m")
    code = cur.get("weather_code")
    hum = cur.get("relative_humidity_2m")
    wind = cur.get("wind_speed_10m")

    def fmt(v, unit="", nd=0):
        if v is None:
            return "—"
        try:
            return f"{round(float(v), nd):g}{unit}"
        except (TypeError, ValueError):
            return "—"

    lines = [f"{resolved} · {wmo_zh(code)} {fmt(temp,'°')}"]
    if hum is not None or wind is not None:
        bits = []
        if hum is not None:
            bits.append(f"湿度{fmt(hum,'%')}")
        if wind is not None:
            bits.append(f"风{fmt(wind,'km/h')}")
        lines.append(" ".join(bits))

    if tmax and tmin:
        today = f"今日 {fmt(tmin[0],'°')}~{fmt(tmax[0],'°')} {wmo_zh(dcode[0] if dcode else None)}"
        if pop and pop[0] is not None and int(pop[0]) >= 10:
            today += f" 雨{int(pop[0])}%"
        lines.append(today)
    if len(tmax) > 1 and len(tmin) > 1:
        tm = f"明日 {fmt(tmin[1],'°')}~{fmt(tmax[1],'°')} {wmo_zh(dcode[1] if len(dcode) > 1 else None)}"
        if pop and len(pop) > 1 and pop[1] is not None and int(pop[1]) >= 10:
            tm += f" 雨{int(pop[1])}%"
        lines.append(tm)
    if uv and uv[0] is not None:
        u = float(uv[0])
        level = "弱" if u < 3 else ("中等" if u < 6 else ("强" if u < 8 else "很强"))
        lines.append(f"紫外线 {round(u)}（{level}）")

    # 珉鸟的一句贴心话
    tips = []
    if pop and pop[0] is not None and int(pop[0]) >= 50:
        tips.append("记得带伞！")
    if tmax and tmax[0] is not None and float(tmax[0]) >= 35:
        tips.append("今天很热，多喝水")
    if tmin and tmin[0] is not None and float(tmin[0]) <= 0:
        tips.append("今天很冷，穿厚点")
    if uv and uv[0] is not None and float(uv[0]) >= 8:
        tips.append("紫外线很强，注意防晒")
    if not tips:
        tips.append("天气不错，出去走走？")
    lines.append(random.choice(tips))

    return "\n".join(lines), (query_city or resolved)


def fetch_balance_raw(api_key: str, timeout: float = 10.0):
    """返回结构化余额：{"currency","total","granted","topped","available"}。
    多币种时优先人民币（消费台阶按 CNY 算才有意义）。
    """
    if not api_key:
        raise RuntimeError("还没填 API Key")

    data = _get_json(DEEPSEEK_BALANCE_URL,
                     headers={"Authorization": f"Bearer {api_key}"},
                     timeout=timeout)

    available = bool(data.get("is_available"))
    rows = data.get("balance_infos") or []
    if not rows:
        raise RuntimeError("没读到余额信息")

    parsed = []
    for r in rows:
        cur_code = r.get("currency", "CNY")
        try:
            parsed.append({
                "currency": cur_code,
                "total": float(r.get("total_balance") or 0),
                "granted": float(r.get("granted_balance") or 0),
                "topped": float(r.get("topped_up_balance") or 0),
            })
        except (TypeError, ValueError):
            continue
    if not parsed:
        raise RuntimeError("余额数据格式不对")

    cny = [p for p in parsed if p["currency"] == "CNY"]
    main = cny[0] if cny else parsed[0]
    main["available"] = available
    main["all"] = parsed
    return main


def fetch_balance(api_key: str, timeout: float = 10.0):
    """返回 (多行情泡文本, raw 结构化数据)。"""
    raw = fetch_balance_raw(api_key, timeout=timeout)
    available = raw["available"]
    rows = raw["all"]
    total_all = []

    lines = []
    for p in rows:
        symbol = "¥" if p["currency"] == "CNY" else "$"
        total_all.append(p["total"])
        lines.append(f"余额 {symbol}{p['total']:.2f}")
        lines.append(f"充值 {symbol}{p['topped']:.2f} · 赠送 {symbol}{p['granted']:.2f}")

    head = "DeepSeek 余额"
    if not available:
        head += "（余额不足）"
    lines.insert(0, head)

    # 快没了就提醒一下
    lowest = min(total_all) if total_all else 0
    if lowest <= 0:
        lines.append("没钱啦，去充值吧！")
    elif lowest < 5:
        lines.append("快见底了，该充值了")
    elif not available:
        lines.append("余额已不足以调用 API")

    return "\n".join(lines), raw


def evaluate_spend(baseline, current, step=1.0):
    """「每花满 step 元提醒一次」的台阶判断。

    返回 (alert, new_baseline)。alert 是 None 或
    {"kind": "spend"|"topup", "amount": float, "current": float}。

    baseline=None 表示第一次读到余额，只记基准不提醒。
    不足一个台阶的零头会留在 baseline 里累计，所以是真的"每满 1 元"，
    而不是"每次查到的差额"。
    """
    try:
        current = float(current)
    except (TypeError, ValueError):
        return None, baseline

    if baseline is None:
        return None, current
    try:
        baseline = float(baseline)
    except (TypeError, ValueError):
        return None, current
    if step <= 0:
        return None, current

    delta = baseline - current
    if delta >= step:
        n = int(delta // step)
        amount = n * step
        return ({"kind": "spend", "amount": amount, "current": current},
                baseline - amount)
    if current > baseline:
        return ({"kind": "topup", "amount": current - baseline,
                 "current": current}, current)
    return None, baseline


# --------------------------------------------------------------------------
# 后台服务
# --------------------------------------------------------------------------
class InfoService:
    """在后台线程跑查询，结果丢进 outbox（queue.Queue）供主线程消费。"""

    def __init__(self, outbox: queue.Queue):
        self.outbox = outbox
        self._busy = threading.Lock()

    def submit(self, task: str, **kwargs) -> None:
        t = threading.Thread(target=self._run, args=(task,), kwargs=kwargs,
                             daemon=True)
        t.start()

    def _run(self, task: str, **kwargs) -> None:
        # 同一时刻只允许一个查询在飞，避免连点刷爆接口
        if not self._busy.acquire(blocking=False):
            return
        try:
            if task == "balance":
                text, raw = fetch_balance(kwargs.get("api_key", ""))
                self.outbox.put(("ok", "balance", text,
                                 {"raw": raw, "verbose": kwargs.get("verbose", True)}))
            elif task == "weather":
                text, city = fetch_weather(kwargs.get("city"))
                extra = {"city": city}
                if kwargs.get("with_date"):
                    extra["with_date"] = True
                self.outbox.put(("ok", "weather", text, extra))
            else:
                self.outbox.put(("err", task, "未知任务", {}))
        except urllib.error.HTTPError as exc:
            code = exc.code
            if code == 401:
                msg = "API Key 不对（401）"
            elif code == 402:
                msg = "余额不足（402）"
            elif code == 429:
                msg = "请求太频繁，等会儿（429）"
            else:
                msg = f"接口返回 {code}"
            self.outbox.put(("err", task, msg, {}))
        except urllib.error.URLError as exc:
            self.outbox.put(("err", task, f"网络连不上：{exc.reason}", {}))
        except Exception as exc:  # noqa: BLE001
            self.outbox.put(("err", task, str(exc) or "查询失败", {}))
        finally:
            self._busy.release()
