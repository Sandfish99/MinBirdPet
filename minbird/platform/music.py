# -*- coding: utf-8 -*-
"""音乐检测探针（平台适配层）：SMTC → 窗口标题 → WASAPI 音频峰值。

实现 core.interfaces.MusicProbe 语义；编排函数 query_music() 给出最终结论。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as wt

from minbird.core.music import match_aespa as _match_aespa
from minbird.platform.proc import _ps
from minbird.platform.win32 import (
    GUID, _com_method, _com_release, _guid_from_str, kernel32, user32)


MUSIC_SMTC_PS = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($WinRtTask, $ResultType) {
  $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
  $netTask = $asTask.Invoke($null, @($WinRtTask))
  $netTask.Wait(-1) | Out-Null
  $netTask.Result
}
$mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
$mgr = Await ($mgrType::RequestAsync()) $mgrType
$sessions = $mgr.GetSessions()
if ($sessions.Count -eq 0) { Write-Output "SMTC_NONE"; exit 0 }
# 探测状态枚举能不能读：读不出来就如实报 PARTIAL，别误报"没在放"
$status = [string]($sessions | Select-Object -First 1).PlaybackStatus
if ([string]::IsNullOrWhiteSpace($status)) { Write-Output "SMTC_PARTIAL"; exit 0 }
$s = $sessions | Where-Object { $_.PlaybackStatus -eq 'Playing' } | Select-Object -First 1
if (-not $s) { Write-Output "SMTC_NONE"; exit 0 }
$propsType = [Windows.Media.Control.GlobalSystemMediaTransportControlsMediaProperties,Windows.Media.Control,ContentType=WindowsRuntime]
$i = Await ($s.TryGetMediaPropertiesAsync()) $propsType
Write-Output ("SMTC_META|{0}|{1}" -f $i.Artist, $i.Title)
""".strip()

PLAYER_PROCESSES = ("qqmusic", "cloudmusic", "kugou", "kuwo", "kwmusic",
                    "spotify", "netease", "orpheus")


TH32CS_SNAPPROCESS = 0x2


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(wt.ULONG)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def _scan_player_windows() -> set:
    """兜底检测：枚举所有顶层窗口（含隐藏/托盘化），返回标题里出现 aespa
    （标题一般是"歌名 - 歌手"）的播放器进程 pid 集合。"""
    kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pids = {}
    if snap:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pids[entry.th32ProcessID] = entry.szExeFile
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        kernel32.CloseHandle(snap)
    hits = set()

    def _on_window(hwnd, _lparam):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = pids.get(pid.value, "").lower()
        if exe and any(p in exe for p in PLAYER_PROCESSES):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                left, sep, right = buf.value.strip().rpartition(" - ")
                if sep and left and _match_aespa(left, right):
                    hits.add(pid.value)
        return True

    cb = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(_on_window)
    user32.EnumWindows(cb, 0)
    return hits


# ---- Core Audio 会话峰值表：判断播放器进程此刻是否真的在出声（暂停检测） ----
_CLS_MMDEVICE_ENUMERATOR = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
_IID_IMMDEVICE_ENUMERATOR = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
_IID_IAUDIO_SESSION_MANAGER2 = "{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}"
_IID_IAUDIO_SESSION_CONTROL2 = "{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}"
_IID_IAUDIO_METER_INFORMATION = "{C02216F6-8C67-4B5B-9D00-D008E73E0064}"



def _process_peak(pids: set) -> float | None:
    """这些进程在默认输出设备上的瞬时峰值（0~1，取最大）；查不到返回 None。"""
    ole32 = ctypes.windll.ole32
    c_void_p, byref = ctypes.c_void_p, ctypes.byref
    p_enum, p_dev, p_mgr, p_enum_s = c_void_p(), c_void_p(), c_void_p(), c_void_p()
    peak = None
    try:
        hr = ole32.CoCreateInstance(byref(_guid_from_str(_CLS_MMDEVICE_ENUMERATOR)),
                                    None, 23,  # CLSCTX_ALL
                                    byref(_guid_from_str(_IID_IMMDEVICE_ENUMERATOR)),
                                    byref(p_enum))
        if hr != 0 or not p_enum:
            return None
        # IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender=0, eMultimedia=1)
        hr = _com_method(p_enum, 4, ctypes.HRESULT, c_void_p, ctypes.c_int,
                         ctypes.c_int, ctypes.POINTER(c_void_p))(p_enum, 0, 1, byref(p_dev))
        _com_release(p_enum)
        if hr != 0 or not p_dev:
            return None
        # IMMDevice::Activate(IAudioSessionManager2)
        hr = _com_method(p_dev, 3, ctypes.HRESULT, c_void_p, GUID, ctypes.c_uint,
                         c_void_p, ctypes.POINTER(c_void_p))(
            p_dev, _guid_from_str(_IID_IAUDIO_SESSION_MANAGER2), 23, None, byref(p_mgr))
        _com_release(p_dev)
        if hr != 0 or not p_mgr:
            return None
        # IAudioSessionManager2::GetSessionEnumerator
        hr = _com_method(p_mgr, 5, ctypes.HRESULT, c_void_p,
                         ctypes.POINTER(c_void_p))(p_mgr, byref(p_enum_s))
        _com_release(p_mgr)
        if hr != 0 or not p_enum_s:
            return None
        count = ctypes.c_int()
        if _com_method(p_enum_s, 3, ctypes.HRESULT, c_void_p,
                       ctypes.POINTER(ctypes.c_int))(p_enum_s, byref(count)) != 0:
            return None
        iid_c2 = _guid_from_str(_IID_IAUDIO_SESSION_CONTROL2)
        iid_meter = _guid_from_str(_IID_IAUDIO_METER_INFORMATION)
        for i in range(count.value):
            p_ctrl, p_c2, p_meter = c_void_p(), c_void_p(), c_void_p()
            if _com_method(p_enum_s, 4, ctypes.HRESULT, c_void_p, ctypes.c_int,
                           ctypes.POINTER(c_void_p))(p_enum_s, i, byref(p_ctrl)) != 0:
                continue
            try:
                _com_method(p_ctrl, 0, ctypes.HRESULT, c_void_p,
                            ctypes.POINTER(GUID), ctypes.POINTER(c_void_p))(
                    p_ctrl, byref(iid_c2), byref(p_c2))
                # GetProcessId 的槽位在新版 Windows 上会移动（实测 12 或 14 都出现过），
                # 哪个槽位读出"进程表里真实存在的 pid"就用哪个
                session_pid = None
                if p_c2:
                    for slot in (14, 12):
                        v = ctypes.c_ulong()
                        try:
                            _com_method(p_c2, slot, ctypes.HRESULT, c_void_p,
                                        ctypes.POINTER(ctypes.c_ulong))(
                                p_c2, byref(v))
                        except OSError:
                            continue
                        if v.value in pids:
                            session_pid = v.value
                            break
                if session_pid is None:
                    continue
                _com_method(p_ctrl, 0, ctypes.HRESULT, c_void_p,
                            ctypes.POINTER(GUID), ctypes.POINTER(c_void_p))(
                    p_ctrl, byref(iid_meter), byref(p_meter))
                if p_meter:
                    val = ctypes.c_float()
                    if _com_method(p_meter, 3, ctypes.HRESULT, c_void_p,
                                   ctypes.POINTER(ctypes.c_float))(
                        p_meter, byref(val)) == 0:
                        peak = max(peak or 0.0, val.value)
            finally:
                _com_release(p_c2)
                _com_release(p_meter)
                _com_release(p_ctrl)
        return peak
    except Exception:
        return peak if peak is not None else None
    finally:
        _com_release(p_enum_s)


def query_music() -> bool:
    """有没有在放 aespa：先问系统媒体会话；读不到就看播放器窗口（含隐藏的），
    标题对上后还要验证播放器此刻真的在出声（暂停/静音就不跳）。"""
    try:
        line = (_ps(MUSIC_SMTC_PS, timeout=15).stdout or "").strip()
    except Exception:
        line = ""
    if line.startswith("SMTC_META|"):
        parts = line.split("|", 2)
        return len(parts) == 3 and _match_aespa(parts[1], parts[2])
    if line == "SMTC_NONE":
        return False   # SMTC 可信：媒体会话正常但没在放
    hit_pids = _scan_player_windows()   # SMTC_PARTIAL / 查询失败
    if not hit_pids:
        return False
    peak = _process_peak(hit_pids)
    if peak is None:
        return True   # 音量峰值读不到就以标题为准
    return peak > 0.02


