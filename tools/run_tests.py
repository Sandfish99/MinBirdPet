# -*- coding: utf-8 -*-
"""统一测试入口：python tools/run_tests.py

聚合仓库里的回归测试（配置回归、selftest、核心纯逻辑单测），
一次跑完，任何一项失败即退出码非 0。架构改造期间这是每一步提交前的门禁。
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

RESULTS = []


def run(name: str, fn=None, cmd: list[str] | None = None, timeout: int = 120) -> None:
    t0 = time.perf_counter()
    try:
        if cmd is not None:
            r = subprocess.run([PY] + cmd, cwd=ROOT, capture_output=True,
                               text=True, timeout=timeout, errors="replace")
            ok = r.returncode == 0
            detail = (r.stdout or r.stderr).strip().splitlines()
            detail = detail[-1] if detail else ""
        else:
            ok = bool(fn())
            detail = ""
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, repr(exc)
    dt = time.perf_counter() - t0
    RESULTS.append((name, ok, dt))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  ({dt:.1f}s) {detail if not ok else ''}")


def unit_aespa_match() -> bool:
    sys.path.insert(0, str(ROOT))
    import minbird_pet as m
    assert m._match_aespa("aespa", "Supernova")
    assert m._match_aespa("AESPA", "drama")
    assert m._match_aespa("x", "에스파 y")
    assert not m._match_aespa("NewJeans", "Ditto")
    assert not m._match_aespa("", "")
    return True


def unit_date_line() -> bool:
    sys.path.insert(0, str(ROOT))
    import minbird_pet as m
    d = m._date_line()
    return "月" in d and "周" in d


def unit_seq_toggle() -> bool:
    """序列帧开关：动态推进 / 静态冻结 / 无素材优雅拒绝。"""
    sys.path.insert(0, str(ROOT))
    import argparse, hashlib
    import minbird_pet as m
    seq = m.load_sprite_seq()
    if seq is None:
        return True  # 仓库缺素材时跳过
    pet = m.Pet(seq[0][0], argparse.Namespace(size=168, walk=True), seq=seq)

    def h(t: float) -> str:
        real = m.time.perf_counter
        m.time.perf_counter = lambda: t
        try:
            return hashlib.md5(pet.compose().tobytes()).hexdigest()
        finally:
            m.time.perf_counter = real

    assert h(0.0) != h(0.9), "动画应随时间推进"
    assert pet.set_seq_mode(False) and h(0.0) == h(0.9), "静态应冻结"
    assert pet.set_seq_mode(True)
    pet.set_size(232)
    assert h(0.0) != h(0.9), "改尺寸后动画仍应推进"
    pet2 = m.Pet(m.Image.open(str(ROOT / "assets/minbird.png")).convert("RGBA").crop((0, 0, 8, 8)),
                 argparse.Namespace(size=40, walk=True), seq=None)
    assert pet2.set_seq_mode(True) is False, "无素材时应拒绝开动画"
    return True


def unit_logging() -> bool:
    sys.path.insert(0, str(ROOT))
    import os, tempfile
    import minbird.logging_setup as ls
    with tempfile.TemporaryDirectory() as td:
        ls.LOG_DIR = td
        ls.LOG_PATH = os.path.join(td, "minbird_pet.log")
        ls.LOG_MAX_BYTES = 4096
        for i in range(200):
            ls.log_line("x" * 64)
        assert os.path.exists(ls.LOG_PATH + ".old"), "应发生日志轮转"
        for i in range(8):
            ls.write_crash_report("test", "boom%d" % i)
        crashes = [f for f in os.listdir(os.path.join(td, "crashes"))
                   if f.startswith("crash_")]
        assert len(crashes) == ls.CRASH_KEEP, f"崩溃文件应保留 {ls.CRASH_KEEP} 份"
    return True


def unit_config_store() -> bool:
    sys.path.insert(0, str(ROOT))
    import json, os, tempfile
    from minbird.config_store import ConfigStore
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "config.json")
        st = ConfigStore(path, defaults=[("city", ""), ("balance_step", 1.0)])

        # 原子写：首写无备份，二写起 .bak 出现
        assert st.write_atomic({"city": ""})
        assert st.write_atomic({"city": "济南"})
        data, broken = st.read()
        assert data["city"] == "济南" and not broken
        assert os.path.exists(path + ".bak"), "第二次写起应生成备份"

        # 主文件损坏：契约是不自动覆盖，只报 broken
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ broken json")
        data, broken = st.load_with_recovery()
        assert broken and data == {}

        # 显式恢复：.bak 写回主路径（.bak 是上一次成功写入的版本），坏文件留证
        assert st.restore_from_backup()
        data, broken = st.read()
        assert not broken and data["city"] == ""
        assert os.path.exists(path + ".broken"), "坏文件应留证"

        # 损坏且无备份：restore 失败，保持 broken
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ still broken")
        os.remove(path + ".bak")
        assert st.restore_from_backup() is False
        data, broken = st.load_with_recovery()
        assert broken and data == {}

        # 迁移：v0 → v1（数值规范化 + 版本号）
        data, changed = st.migrate({"balance_step": "2", "size": "232", "x": "10"})
        assert changed and data["config_version"] == 1
        assert data["balance_step"] == 2.0 and data["size"] == 232 and data["x"] == 10.0
        data2, changed2 = st.migrate(data)
        assert not changed2, "已迁移的不应再改"
    return True


def unit_safemode() -> bool:
    sys.path.insert(0, str(ROOT))
    import json, os, tempfile
    from minbird.core.safemode import next_streak, safe_mode_required
    from minbird.platform.state import load_state, save_state
    assert next_streak({}) == 0
    assert next_streak({"clean": True}) == 0
    assert next_streak({"clean": False, "run_streak": 2}) == 3
    assert next_streak({"clean": False, "run_streak": "x"}) == 1
    assert safe_mode_required(3) and not safe_mode_required(2)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "runtime_state.json")
        save_state(path, {"clean": False, "run_streak": 2})
        assert load_state(path)["run_streak"] == 2
        assert next_streak(load_state(path)) == 3
        save_state(path, {"clean": True, "run_streak": 0})
        assert next_streak(load_state(path)) == 0
    return True


def unit_update_swap() -> bool:
    sys.path.insert(0, str(ROOT))
    import os, tempfile
    from minbird.platform.update_swap import _rollback_in, _swap_in
    with tempfile.TemporaryDirectory() as td:
        cur = os.path.join(td, "MinBirdPet.exe")
        pending = os.path.join(td, "MinBirdPet_new.exe")
        prev = os.path.join(td, "MinBirdPet_prev.exe")
        bad = os.path.join(td, "MinBirdPet_bad.exe")

        # 无 pending：不动作
        assert _swap_in(cur, pending, prev) is False

        # 正常交换：cur→prev，pending→cur
        open(cur, "wb").write(b"old")
        open(pending, "wb").write(b"new")
        assert _swap_in(cur, pending, prev) is True
        assert open(cur, "rb").read() == b"new"
        assert open(prev, "rb").read() == b"old"
        assert not os.path.exists(pending)

        # 回滚：cur→bad，prev→cur
        assert _rollback_in(cur, prev, bad) is True
        assert open(cur, "rb").read() == b"old"
        assert open(bad, "rb").read() == b"new"

        # 无 prev：回滚失败且现状不动（上一次回滚已消耗掉 prev）
        assert not os.path.exists(prev)
        data = open(cur, "rb").read()
        assert _rollback_in(cur, prev, bad) is False
        assert open(cur, "rb").read() == data
    return True


def unit_resource_limits() -> bool:
    sys.path.insert(0, str(ROOT))
    import os, tempfile
    from minbird.platform.memory import current_rss_mb
    rss = current_rss_mb()
    assert rss is not None and rss > 0, "RSS 查询应可用"
    # alerts 队列上限：超过 50 行只留最新的
    import minbird_pet as m
    with tempfile.TemporaryDirectory() as td:
        old_path, old_dir = m.ALERT_PATH, m.CONFIG_DIR
        m.ALERT_PATH = os.path.join(td, "alerts.jsonl")
        m.CONFIG_DIR = td
        try:
            for i in range(60):
                m._append_alert(f"提醒{i}")
            lines = open(m.ALERT_PATH, encoding="utf-8").read().splitlines()
            assert len(lines) == 50, f"应截断到 50 行，实际 {len(lines)}"
            assert "提醒59" in lines[-1], "应保留最新的"
        finally:
            m.ALERT_PATH, m.CONFIG_DIR = old_path, old_dir
    return True


def unit_multimonitor() -> bool:
    sys.path.insert(0, str(ROOT))
    from minbird.core import geom
    from minbird.core.interfaces import Rect

    class R:  # 最小鸭子矩形
        def __init__(self, l, t, r, b):
            self.left, self.top, self.right, self.bottom = l, t, r, b

    wa = R(0, 0, 1920, 1040)
    assert geom.clamp_into(wa, -50, 2000) == (8, 1038)
    rx, ry = geom.relative_of(wa, 960, 520)
    assert abs(rx - 0.5) < 1e-9 and abs(ry - 0.5) < 1e-9
    x, y = geom.point_from_relative(wa, 0.25, 0.75)
    assert abs(x - 480) < 1e-6 and abs(y - 780) < 1e-6

    # 实测：本机至少一块屏，工作区在虚拟桌面内
    from minbird.platform import monitors
    areas = monitors.work_areas()
    assert len(areas) >= 1
    vx0, vy0, vx1, vy1 = monitors.virtual_screen()
    for a in areas:
        assert vx0 <= a.left and a.right <= vx1 and vy0 <= a.top and a.bottom <= vy1
    pa = monitors.work_area_for_point(1, 1)
    assert pa.right > pa.left and pa.bottom > pa.top
    return True


def unit_env_detect() -> bool:
    sys.path.insert(0, str(ROOT))
    from minbird.platform.env import is_remote_session, vm_markers_hit
    assert vm_markers_hit("Intel(R) Core(TM) VMware Virtual Platform") == ["vmware"]
    assert "virtualbox" in vm_markers_hit("VirtualBox BIOS")
    assert vm_markers_hit("ASUSTeK PRIME B550") == []
    # 实测：本机是否 RDP/VM 只记录不判定（两种结果都合法）
    print("remote:", is_remote_session(), "| vm:", __import__(
        "minbird.platform.env", fromlist=["x"]).is_virtual_machine())
    return True


def main() -> int:
    print(f"== MinBirdPet 回归测试 ({PY}) ==")
    run("unit: aespa 匹配", unit_aespa_match)
    run("unit: 日期文案", unit_date_line)
    run("unit: 日志轮转与崩溃清理", unit_logging)
    run("unit: 配置存储（原子/备份/迁移）", unit_config_store)
    run("unit: 安全模式判定与状态文件", unit_safemode)
    run("unit: 更新交换与回滚", unit_update_swap)
    run("unit: 资源限制（RSS/提醒上限）", unit_resource_limits)
    run("兼容: DPI 感知 PMv2", cmd=["tools/verify_dpi.py"])
    run("兼容: 多显示器几何与枚举", unit_multimonitor)
    run("兼容: 全屏检测", cmd=["tools/verify_fullscreen.py"])
    run("兼容: 点击穿透实测", cmd=["tools/verify_clickthrough.py"])
    run("兼容: RDP/VM 环境探测", unit_env_detect)
    run("兼容: 便携性/权限审计", cmd=["tools/audit_portable.py"])
    run("unit: 番茄钟核心", cmd=["tools/test_pomodoro.py"])
    run("unit: 设置注册表", cmd=["tools/test_settings_registry.py"])
    run("unit: 序列帧开关", unit_seq_toggle)
    run("回归: 配置文件不被覆盖", cmd=["tools/test_config.py"])
    run("回归: selftest 渲染", cmd=["minbird_pet.py", "--selftest"])
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"== {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ==")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
