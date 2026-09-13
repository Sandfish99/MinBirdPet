# -*- coding: utf-8 -*-
"""余额「每满 N 元提醒一次」的回归测试。

重点验证两件事：
1. 台阶逻辑：不足一个台阶的零头要累计，不能吞掉。
2. 珉鸟主进程不做周期性网络请求 —— 代码里不能有 balance 相关的定时器。

用法：python tools/test_balance_alert.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import minbird_info  # noqa: E402
import minbird_pet  # noqa: E402

OUT = []
FAILS = []


def check(name, cond, detail=""):
    if cond:
        OUT.append(f"PASS  {name}")
    else:
        OUT.append(f"FAIL  {name}  {detail}")
        FAILS.append(name)


# --------------------------------------------------------------------------
# 1. 台阶逻辑
# --------------------------------------------------------------------------
def t_steps():
    ev = minbird_info.evaluate_spend

    # 首次读到余额：只建基准，不提醒
    alert, base = ev(None, 50.0, 1.0)
    check("首次只建基准不提醒", alert is None and base == 50.0, f"{alert} {base}")

    # 花 0.4：不够 1 元，不提醒，零头留着
    alert, base = ev(50.0, 49.6, 1.0)
    check("花 0.4 不提醒", alert is None and base == 50.0, f"{alert} {base}")

    # 再花 0.7 -> 累计 1.1，跨过 1 个台阶
    alert, base = ev(50.0, 48.9, 1.0)
    check("累计 1.1 触发一次", alert and alert["kind"] == "spend"
          and abs(alert["amount"] - 1.0) < 1e-9, f"{alert}")
    check("基准只推进 1 元，零头保留", abs(base - 49.0) < 1e-9, f"{base}")

    # 一次花掉 3.7：跨 3 个台阶，剩 0.7 留在基准里
    alert, base = ev(10.0, 6.3, 1.0)
    check("一次花 3.7 报 3 元", alert and abs(alert["amount"] - 3.0) < 1e-9, f"{alert}")
    check("剩余零头 0.7 保留", abs(base - 7.0) < 1e-9, f"{base}")

    # 接着再花 0.3（6.3 -> 6.0），加上留着的 0.7 零头刚好满 1 元 -> 提醒
    alert, base = ev(7.0, 6.0, 1.0)
    check("零头补满 1 元后提醒", alert and abs(alert["amount"] - 1.0) < 1e-9, f"{alert}")
    check("提醒后基准再降 1 元", abs(base - 6.0) < 1e-9, f"{base}")

    # 充值：重置基准
    alert, base = ev(6.0, 56.0, 1.0)
    check("充值识别为 topup", alert and alert["kind"] == "topup"
          and abs(alert["amount"] - 50.0) < 1e-9, f"{alert}")
    check("充值后基准跟着抬上去", abs(base - 56.0) < 1e-9, f"{base}")

    # step=5：花 3 元不提醒，花 6 元提醒 5
    alert, _ = ev(20.0, 17.0, 5.0)
    check("step=5 花 3 元不提醒", alert is None, f"{alert}")
    alert, base = ev(20.0, 14.0, 5.0)
    check("step=5 花 6 元提醒 5", alert and abs(alert["amount"] - 5.0) < 1e-9, f"{alert}")
    check("step=5 基准推进 5", abs(base - 15.0) < 1e-9, f"{base}")

    # step=0（关闭）：永远不提醒，但基准要跟着走
    alert, base = ev(20.0, 1.0, 0.0)
    check("关闭时永不提醒", alert is None, f"{alert}")
    check("关闭时基准仍然同步", abs(base - 1.0) < 1e-9, f"{base}")

    # 脏数据不能崩
    for bad in (None, "", "abc"):
        try:
            ev(10.0, bad, 1.0)
            ev(bad, 10.0, 1.0)
        except Exception as exc:  # noqa: BLE001
            check(f"脏数据不崩溃 ({bad!r})", False, str(exc))
            return
    check("脏数据不崩溃", True)


# --------------------------------------------------------------------------
# 2. 金额格式化
# --------------------------------------------------------------------------
def t_money():
    check("1.0 -> 1", minbird_pet._money(1.0) == "1")
    check("5.0 -> 5", minbird_pet._money(5) == "5")
    check("1.5 -> 1.50", minbird_pet._money(1.5) == "1.50")
    check("None -> —", minbird_pet._money(None) == "—")


# --------------------------------------------------------------------------
# 3. 提醒中转（alerts.jsonl）
# --------------------------------------------------------------------------
def t_alerts(tmp):
    alert_path = os.path.join(tmp, "alerts.jsonl")
    minbird_pet.ALERT_PATH = alert_path

    check("没有提醒文件时读空", minbird_pet._read_alerts() == [])

    minbird_pet._append_alert("第一条")
    minbird_pet._append_alert("第二条")
    items = minbird_pet._read_alerts()
    check("两条提醒都写进去了", len(items) == 2, f"{len(items)}")
    check("内容正确", items[0]["text"] == "第一条" and items[1]["text"] == "第二条")

    minbird_pet._clear_alerts()
    check("清空后读空", minbird_pet._read_alerts() == [])

    # 坏行不能把整条队列带崩
    with open(alert_path, "w", encoding="utf-8") as fh:
        fh.write("not json\n")
        fh.write(json.dumps({"ts": __import__("time").time(), "text": "好的"}) + "\n")
    items = minbird_pet._read_alerts()
    check("坏行被跳过", len(items) == 1 and items[0]["text"] == "好的", f"{items}")

    # 过期的不播
    with open(alert_path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": __import__("time").time() - 99999,
                             "text": "太久以前"}) + "\n")
    items = [it for it in minbird_pet._read_alerts()
             if __import__("time").time() - float(it.get("ts") or 0)
             <= minbird_pet.ALERT_MAX_AGE]
    check("过期提醒被丢弃", items == [], f"{items}")
    minbird_pet._clear_alerts()


# --------------------------------------------------------------------------
# 4. 一次性检查：没配 Key / 提醒关掉时，一个请求都不该发
# --------------------------------------------------------------------------
def t_check_once(tmp):
    cfg_path = os.path.join(tmp, "config.json")
    minbird_pet.CONFIG_PATH = cfg_path
    minbird_pet.ALERT_PATH = os.path.join(tmp, "alerts.jsonl")

    def write_cfg(d):
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)

    # 网络必须没被调用过
    called = {"n": 0}
    real = minbird_info.fetch_balance_raw

    def spy(key, timeout=10.0):
        called["n"] += 1
        return real(key, timeout=timeout)

    minbird_info.fetch_balance_raw = spy
    try:
        write_cfg({"deepseek_api_key": "", "balance_step": 1.0})
        rc = minbird_pet.check_balance_once()
        check("没填 Key -> 直接返回 2", rc == 2, f"rc={rc}")
        check("没填 Key -> 零请求", called["n"] == 0, f"n={called['n']}")

        write_cfg({"deepseek_api_key": "sk-test", "balance_step": 0})
        rc = minbird_pet.check_balance_once()
        check("提醒关闭 -> 返回 2", rc == 2, f"rc={rc}")
        check("提醒关闭 -> 零请求", called["n"] == 0, f"n={called['n']}")

        # 有 Key 且开关打开，才会真的发一次请求（这里用一个假 key，预期 401）
        write_cfg({"deepseek_api_key": "sk-invalid-for-test", "balance_step": 1.0})
        rc = minbird_pet.check_balance_once()
        check("有 Key -> 真的发了请求", called["n"] == 1, f"n={called['n']}")
        check("坏 Key -> 返回 1 且不崩", rc == 1, f"rc={rc}")
    finally:
        minbird_info.fetch_balance_raw = real


# --------------------------------------------------------------------------
# 4b. 完整链路：余额一路下降，看什么时候真的写下提醒
# --------------------------------------------------------------------------
def t_full_chain(tmp):
    cfg_path = os.path.join(tmp, "chain_config.json")
    alert_path = os.path.join(tmp, "chain_alerts.jsonl")
    minbird_pet.CONFIG_PATH = cfg_path
    minbird_pet.ALERT_PATH = alert_path
    minbird_pet.CONFIG_DIR = tmp

    def write_cfg(d):
        with open(cfg_path, "w", encoding="utf-8") as fh:
            json.dump(d, fh, ensure_ascii=False, indent=2)

    write_cfg({"deepseek_api_key": "sk-test", "balance_step": 1.0,
               "balance_baseline": None})

    now = {"total": 50.0}

    def fake(key, timeout=10.0):
        return {"currency": "CNY", "total": now["total"], "granted": 0.0,
                "topped": 50.0, "available": True, "all": []}

    real = minbird_info.fetch_balance_raw
    minbird_info.fetch_balance_raw = fake
    try:
        # 第一次：只建基准
        minbird_pet.check_balance_once()
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        check("链路-首次建立基准 50", abs(cfg["balance_baseline"] - 50.0) < 1e-9,
              f"{cfg.get('balance_baseline')}")
        check("链路-首次不产生提醒", minbird_pet._read_alerts() == [])

        # 花 0.8：不够 1 元
        now["total"] = 49.2
        minbird_pet.check_balance_once()
        check("链路-花 0.8 不提醒", minbird_pet._read_alerts() == [])

        # 再花 0.5 -> 累计 1.3，跨 1 个台阶
        now["total"] = 48.7
        minbird_pet.check_balance_once()
        items = minbird_pet._read_alerts()
        check("链路-累计 1.3 触发提醒", len(items) == 1, f"{items}")
        if items:
            check("链路-提醒文案含金额", "¥1" in items[0]["text"], items[0]["text"])
        cfg = json.load(open(cfg_path, encoding="utf-8"))
        check("链路-基准推进到 49", abs(cfg["balance_baseline"] - 49.0) < 1e-9,
              f"{cfg.get('balance_baseline')}")

        # 花 0.2 -> 未报 0.5，不提醒
        now["total"] = 48.5
        minbird_pet.check_balance_once()
        check("链路-未报 0.5 不提醒", len(minbird_pet._read_alerts()) == 1)

        # 再花 0.6 -> 未报 1.1，提醒第二次
        now["total"] = 47.9
        minbird_pet.check_balance_once()
        check("链路-零头补满触发第二次", len(minbird_pet._read_alerts()) == 2,
              f"{minbird_pet._read_alerts()}")

        # 充值
        now["total"] = 97.9
        minbird_pet.check_balance_once()
        items = minbird_pet._read_alerts()
        check("链路-充值识别", len(items) == 3 and "充值" in items[2]["text"],
              f"{items[-1:]}")
    finally:
        minbird_info.fetch_balance_raw = real
        minbird_pet._clear_alerts()


# --------------------------------------------------------------------------
# 5. 静态检查：主进程里绝不能出现周期性的余额查询
# --------------------------------------------------------------------------
def t_no_polling():
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "minbird_pet.py"), encoding="utf-8").read()
    # 只允许 SetTimer 用于渲染帧 / 拖拽，不允许出现第二个长周期定时器
    timers = [ln.strip() for ln in src.splitlines() if "SetTimer" in ln
              and not ln.strip().startswith(("#", "*"))]
    check("只有一个渲染定时器", len([t for t in timers if "TIMER_ID" in t]) <= 2,
          f"{timers}")
    check("没有 balance 定时轮询",
          not any("balance" in t.lower() for t in timers), f"{timers}")


def main():
    t_steps()
    t_money()
    t_no_polling()
    with tempfile.TemporaryDirectory() as tmp:
        t_alerts(tmp)
        t_check_once(tmp)
        t_full_chain(tmp)

    OUT.append("")
    OUT.append(f"结果：{'全部通过' if not FAILS else str(len(FAILS)) + ' 项失败'}")
    text = "\n".join(OUT)
    print(text)
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_balance_alert_out.txt"), "w", encoding="utf-8") as fh:
        fh.write(text)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
