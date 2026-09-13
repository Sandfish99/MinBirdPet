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


def main() -> int:
    print(f"== MinBirdPet 回归测试 ({PY}) ==")
    run("unit: aespa 匹配", unit_aespa_match)
    run("unit: 日期文案", unit_date_line)
    run("unit: 日志轮转与崩溃清理", unit_logging)
    run("unit: 序列帧开关", unit_seq_toggle)
    run("回归: 配置文件不被覆盖", cmd=["tools/test_config.py"])
    run("回归: selftest 渲染", cmd=["minbird_pet.py", "--selftest"])
    failed = [n for n, ok, _ in RESULTS if not ok]
    print(f"== {len(RESULTS) - len(failed)}/{len(RESULTS)} 通过 ==")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
