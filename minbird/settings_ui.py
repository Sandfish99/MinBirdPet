# -*- coding: utf-8 -*-
"""珉鸟设置中心（pywebview + WebView2，HTML 单页）。

- 设置项全部来自 core.settings_registry（分类/类型/默认值/生效分发键）
- 顶部搜索 + 分类 chips 实时过滤；开关/数字/枚举/文本控件
- 高级动作：日志导出/配置备份/恢复/导入导出/恢复默认值（原生文件对话框）
- 「保存」→ app.apply_settings（注册表 coerce → 原子落盘 → 即时生效分发）
"""
from __future__ import annotations

import json
import os

import webview

from minbird.core import settings_registry as sr

HTML = r"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
 body{font-family:"Microsoft YaHei UI",system-ui;margin:0;background:#eef0f4;color:#262830}
 header{position:sticky;top:0;z-index:3;background:#fff;padding:12px 16px 10px;
        border-bottom:1px solid #e2e4ea;box-shadow:0 1px 4px rgba(0,0,0,.04)}
 #q{width:100%;box-sizing:border-box;padding:8px 12px;border:1px solid #d6d9e0;
    border-radius:8px;font-size:14px;outline:none}
 #chips{margin-top:10px;display:flex;gap:8px;flex-wrap:wrap}
 .chip{padding:4px 12px;border-radius:999px;border:1px solid #d6d9e0;background:#fff;
       cursor:pointer;font-size:13px}
 .chip.on{background:#3a7afe;color:#fff;border-color:#3a7afe}
 main{padding:10px 14px 76px}
 .row{display:flex;justify-content:space-between;align-items:center;gap:12px;
      background:#fff;border:1px solid #e2e4ea;border-radius:10px;
      padding:10px 14px;margin:8px 0}
 .row .lab{font-size:14px}
 .row .hint{font-size:12px;color:#8a8f9c;margin-top:2px}
 input[type=number],input[type=text],select{padding:6px 10px;border:1px solid #d6d9e0;
      border-radius:8px;font-size:14px;width:150px;background:#fff;outline:none}
 .sw{position:relative;width:42px;height:22px;background:#cfd3dc;border-radius:999px;
     cursor:pointer;transition:background .15s}
 .sw.on{background:#3a7afe}
 .sw::after{content:"";position:absolute;top:2px;left:2px;width:18px;height:18px;
     border-radius:50%;background:#fff;transition:left .15s}
 .sw.on::after{left:22px}
 button.act{padding:7px 14px;border:1px solid #d6d9e0;border-radius:8px;background:#fff;
      cursor:pointer;font-size:13px}
 button.act:hover{background:#f2f4f8}
 footer{position:fixed;bottom:0;right:0;padding:10px 16px;z-index:3}
 footer button{padding:8px 22px;border:none;border-radius:8px;background:#3a7afe;
      color:#fff;font-size:14px;cursor:pointer}
 #toast{position:fixed;left:50%;top:18px;transform:translateX(-50%);
      background:#262830;color:#fff;padding:8px 18px;border-radius:8px;
      font-size:13px;display:none;z-index:9}
</style></head>
<body>
<header>
  <input id="q" placeholder="搜索设置…" oninput="render()">
  <div id="chips"></div>
</header>
<main id="list"></main>
<footer><button onclick="save()">保 存</button></footer>
<div id="toast"></div>
<script>
let items = [], values = {}, safe = false;
let cat = "全部", q = "";
const CATS = ["全部","宠物","行为","番茄钟","外观","高级"];

async function boot(){
  try {
    const m = await pywebview.api.get_model();
    items = m.items; values = {}; safe = m.safe;
    if (m.broken) toast("配置文件损坏，改动将无法保存");
    renderChips(); render();
    pywebview.api.log_loaded(document.getElementById("list").children.length);
  } catch (e) {
    const list = document.getElementById("list");
    list.innerHTML = "<div style='padding:30px;color:#c0392b'>加载失败：" + e + "</div>";
  }
}

// pywebview 桥接在 DOMContentLoaded 之后才注入，必须等 pywebviewready
window.addEventListener("pywebviewready", boot);
window.addEventListener("DOMContentLoaded", () => {
  if (window.pywebview && pywebview.api) boot();
  else { let n = 0;
    const t = setInterval(() => {
      n += 1;
      if (window.pywebview && pywebview.api) { clearInterval(t); boot(); }
      else if (n > 40) { clearInterval(t);
        document.getElementById("list").innerHTML =
          "<div style='padding:30px;color:#c0392b'>桥接初始化超时</div>"; }
    }, 100);
  }
});

function toast(t){ const el = document.getElementById("toast");
  el.textContent = t; el.style.display = "block";
  clearTimeout(el._h); el._h = setTimeout(() => el.style.display = "none", 2200); }

function renderChips(){
  const box = document.getElementById("chips"); box.innerHTML = "";
  for (const c of CATS){
    const b = document.createElement("button");
    b.className = "chip" + (c === cat ? " on" : ""); b.textContent = c;
    b.onclick = () => { cat = c; renderChips(); render(); };
    box.appendChild(b);
  }
}

function visible(i){
  const hay = (i.label + i.key + i.cat).toLowerCase();
  if (q && !hay.includes(q.toLowerCase())) return false;
  return cat === "全部" || i.cat === cat;
}

function render(){
  const list = document.getElementById("list"); list.innerHTML = "";
  for (const i of items){
    if (!visible(i)) continue;
    const row = document.createElement("div"); row.className = "row";
    const lab = document.createElement("div"); lab.className = "lab";
    lab.textContent = i.label;
    if (i.hint){ const h = document.createElement("div"); h.className = "hint";
                 h.textContent = i.hint; lab.appendChild(h); }
    row.appendChild(lab);
    let ctl;
    if (i.type === "action"){
      ctl = document.createElement("button"); ctl.className = "act";
      ctl.textContent = "执行";
      ctl.onclick = () => pywebview.api.run_action(i.key).then(t => { if (t) toast(t); });
    } else if (i.type === "bool"){
      ctl = document.createElement("div");
      ctl.className = "sw" + (values[i.key] ? " on" : "");
      ctl.onclick = () => { values[i.key] = !values[i.key];
                            ctl.className = "sw" + (values[i.key] ? " on" : ""); };
    } else if (i.type === "enum"){
      ctl = document.createElement("select");
      i.choices.forEach((d, idx) => {
        const o = document.createElement("option"); o.textContent = d;
        o.value = String(idx);
        if (String(i.values[idx]) === String(values[i.key])) o.selected = true;
        ctl.appendChild(o);
      });
      ctl.onchange = () => { values[i.key] = i.values[ctl.selectedIndex]; };
    } else if (i.type === "int"){
      ctl = document.createElement("input"); ctl.type = "number";
      ctl.value = values[i.key];
      ctl.onchange = () => { values[i.key] = ctl.value; };
    } else {
      ctl = document.createElement("input"); ctl.type = "text";
      ctl.value = values[i.key] || "";
      ctl.onchange = () => { values[i.key] = ctl.value; };
    }
    row.appendChild(ctl); list.appendChild(row);
  }
  if (!list.children.length){
    const e = document.createElement("div");
    e.style.cssText = "text-align:center;color:#8a8f9c;padding:30px";
    e.textContent = "没有匹配的设置项"; list.appendChild(e);
  }
}

function save(){
  pywebview.api.apply(values).then(r => {
    if (r === "BROKEN"){ toast("配置文件读不懂啦，先修复 JSON"); return; }
    toast("设置已保存并生效");
  });
}
</script></body></html>"""


class Api:
    """暴露给 HTML 的桥接对象（pywebview js_api）。独立进程版：直接读写配置存储。"""

    def __init__(self, store, defaults, log_path, window):
        self.store = store
        self.defaults = list(defaults)
        self.log_path = log_path
        self._window = window

    def _current(self) -> tuple:
        data, broken = self.store.read()
        data, _ = self.store.ensure_defaults(data)
        return data, broken

    def get_model(self):
        data, broken = self._current()
        items = []
        for i in sr.ITEMS:
            if i.type == "action":
                items.append({"key": i.key, "cat": i.category, "type": "action",
                              "label": i.label})
                continue
            entry = {"key": i.key, "cat": i.category, "type": i.type,
                     "label": i.label, "value": data.get(i.key, i.default)}
            if i.type == "enum":
                entry["choices"] = list(i.choices)
                entry["values"] = [str(v) for v in (i.choices_map or i.choices)]
                entry["value"] = str(entry["value"])
            items.append(entry)
        return {"items": items, "broken": broken}

    def apply(self, values):
        if not isinstance(values, dict):
            return "ERR"
        data, broken = self._current()
        if broken:
            return "BROKEN"
        for key, value in values.items():
            item = sr.BY_KEY.get(key)
            if item is not None and item.type != "action":
                data[key] = sr.coerce(item, value)
        self.store.write_atomic(data)   # 珉鸟进程的配置监听 2 秒内自动应用
        return "OK"

    def log_loaded(self, count: int) -> None:
        """HTML 启动完成后回报渲染行数（诊断：桥接/渲染是否正常）。"""
        from minbird.logging_setup import log_line
        log_line("settings ui loaded,", count, "rows")

    def run_action(self, action: str):
        if action == "backup":
            data, _ = self._current()
            self.store.write_atomic(data)
            return "配置已备份到 .bak"
        if action == "restore_bak":
            if self.store.restore_from_backup():
                return "已从备份恢复配置"
            return "没有可用的备份"
        if action == "reset_all":
            data, _ = self._current()
            keep = {k: data[k] for k in ("x", "y") if k in data}
            data = dict(keep)
            data, _ = self.store.ensure_defaults(data)
            data, _ = self.store.migrate(data)
            self.store.write_atomic(data)
            return "已恢复默认设置（位置保留）"
        if action in ("export_log", "export_cfg"):
            name = "minbird_pet.log" if action == "export_log" else "minbird_config.json"
            ftypes = ("日志 (*.log)",) if action == "export_log" else ("JSON (*.json)",)
            paths = self._window.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=name, file_types=ftypes)
            if paths:
                path = paths if isinstance(paths, str) else paths[0]
                try:
                    import shutil
                    if action == "export_log":
                        if os.path.exists(self.log_path):
                            shutil.copyfile(self.log_path, path)
                            return "导出啦"
                        return "日志文件不存在"
                    with open(path, "w", encoding="utf-8") as fh:
                        data, _ = self._current()
                        json.dump(data, fh, ensure_ascii=False, indent=2)
                    return "导出啦"
                except OSError:
                    return "导出失败"
            return ""
        if action == "import_cfg":
            paths = self._window.create_file_dialog(
                webview.OPEN_DIALOG, file_types=("JSON (*.json)",))
            if paths:
                path = paths if isinstance(paths, str) else paths[0]
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if not isinstance(data, dict):
                        raise ValueError("not a dict")
                    self.store.write_atomic(data)
                    return "导入啦，珉鸟 2 秒内自动生效"
                except (OSError, ValueError):
                    return "导入失败，检查格式"
            return ""
        return ""


def open_settings(store, defaults, log_path) -> None:
    """在当前进程主线程运行设置窗口（阻塞至关闭）。由 --settings 入口调用。"""
    api = Api(store, defaults, log_path, None)
    window = webview.create_window("珉鸟设置", html=HTML, width=560, height=680,
                                   min_size=(480, 560), js_api=api)
    api._window = window
    webview.start(gui="edgechromium")
