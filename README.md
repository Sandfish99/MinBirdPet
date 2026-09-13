# 珉鸟桌宠 / MinBird Desktop Pet

![Platform](https://img.shields.io/badge/platform-Windows-0078D6) ![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB) ![License](https://img.shields.io/badge/license-MIT-green) ![Release](https://img.shields.io/github/v/release/Sandfish99/MinBirdPet)

把「珉鸟」—— aespa 成员 Karina（柳智敏）的小鸟表情包形象 —— 做成一只住在 Windows 桌面上的桌宠。

> 本项目为非官方粉丝作品，与 aespa 及 SM Entertainment 无关；珉鸟形象版权归原作者及相关权利人所有。

![珉鸟](assets/_preview_light.png)

---

## 一、怎么启动

三种方式，任选一种：

| 方式 | 操作 | 说明 |
| --- | --- | --- |
| **推荐** | 从 [Releases](../../releases/latest) 下载 `MinBirdPet.exe`，双击运行 | 免安装、免依赖，单个文件，随时可删 |
| 脚本启动 | 双击 `start-minbird-pet.vbs` | 优先跑 exe，没有 exe 时回退到 Python 源码 |
| 开发模式 | `pip install -r requirements.txt` 后 `python minbird_pet.py` | 需要 Python + Pillow |

启动后珉鸟会站在任务栏上方偏右的位置。**首次启动会自动记住位置，下次还在原地。**

## 二、能玩什么

| 操作 | 反应 |
| --- | --- |
| **左键单击** | 蹦一下 + 随机说一句话（"啾~""摸摸头""今天也要加油鸭"……） |
| **左键拖动** | 拎起来甩，身体会跟着惯性倾斜、回弹；松手太用力会飞出去，落地还会弹两下 |
| **右键单击珉鸟** | 打开菜单（见下） |
| **待机** | 呼吸、眨眼、歪头循环播放（绿幕视频切帧的实拍质感），偶尔小跳 |
| **平时** | 每隔几秒自己溜达到屏幕另一头（可关） |
| **在窗口上** | 会落到应用窗口的标题栏上站着、散步；走出窗沿、窗口被拖走或关掉都会掉下去。把珉鸟甩到窗口上半部，它会扑棱一把站上标题栏 |
| **放着 aespa 的歌** | 开了「听到 aespa 就跳舞」后，珉鸟会左右摇摆、上下蹦跶，歌一停就站好。优先走系统媒体接口；读不到时自动扫描播放器的窗口标题（含隐藏/托盘化的窗口，播放器主窗口关掉也能识别），安静跳舞、不弹气泡 |
| **开机后第一次启动** | 自动说一声今天的日期，再查一次今日天气（仅此一次，不打扰） |

右键菜单：

```
摸摸头
☑ 自己散步        ← 点一下切换（关掉就乖乖站着）
☑ 能在窗口上走     ← 站/走在应用窗口的标题栏上（关掉就只待任务栏）
☑ 待机动画        ← 呼吸/眨眼/歪头序列帧（关掉回静态图，选择会被记住）
☑ 听到 aespa 就跳舞 ← 放 aespa 的歌就摇摆蹦跶，歌停站好
尺寸：中（点击切换）  ← 小 / 中 / 大 / 特大 循环
☑ 总在最前
☐ 开机自启        ← 点一下写入/移除注册表启动项
──────────────
看看 DeepSeek 余额      ← 珉鸟头顶弹出余额
余额提醒：每 ¥1         ← 每花满多少元喊你一次（¥1/¥5/¥10/关）
自动查余额：未开启       ← 开 = 交给 Windows 计划任务每小时查一次
今天天气怎么样          ← 弹出当前天气 + 今明两天预报
设置                   ← 打开设置窗口（Key / 城市 / 尺寸 / 各开关）
──────────────
藏起来            ← 收进托盘，点托盘图标再出来
让珉鸟下班（退出）  ← 保存位置后干净退出
```

托盘图标（任务栏右下角）也有同样的菜单，**左键点托盘图标 = 显示/隐藏**。
透明区域是**点击穿透**的，只有戳到珉鸟身体才会响应，不会挡住你干活。

## 三、文件说明

```
MinBirdPet/
├── minbird_pet.py            主程序源码（Win32 分层窗口 + Pillow 合成）
├── minbird_info.py           信息服务（DeepSeek 余额 / 天气，零第三方依赖）
├── start-minbird-pet.vbs     静默启动器
├── MinBirdPet.spec           PyInstaller 配置（相对路径，可直接打包）
├── requirements.txt          运行依赖（Pillow）
├── requirements-dev.txt      打包依赖（PyInstaller）
├── LICENSE                   MIT 许可证
├── assets/
│   ├── minbird.png           抠好的透明底宠物图（388×497）
│   ├── minbird_flip.png      镜像版
│   ├── minbird.ico           托盘/程序图标
│   ├── seq/                  序列帧待机动画（sheet.png + manifest.json）
│   ├── _preview_light.png    白底预览
│   ├── _preview_dark.png     暗色桌面预览
│   └── _bubble_preview.png   三种气泡状态对比图
└── tools/                    素材处理与自检脚本
    ├── make_seq.py           绿幕视频 → 序列帧素材（去水印 / 色键抠像 / 找无缝循环）
    ├── make_assets.py        最初的轮廓法抠图（已被 AI 抠图取代，留作记录）
    ├── finalize_assets.py    裁切、生成图标与预览
    ├── smoke.py              冒烟测试（建窗口、渲染、菜单命令）
    ├── verify_screen.py      启动并截屏验证
    ├── test_info.py          余额/天气自检（接口 + 多行气泡 + 位移检查）
    ├── test_balance_alert.py 余额台阶提醒自检（含完整消费链路模拟）
    ├── test_config.py        配置文件不被程序覆盖的回归测试
    ├── test_surfaces.py      窗口表面检测自检（枚举 + 站沿 + 掉落）
    ├── demo_window_perch.py  端到端演示：让珉鸟落上临时记事本的标题栏并截图
    └── bench.py              渲染性能测试
```

打包好的 `MinBirdPet.exe` 不放在仓库里，统一走 [Releases](../../releases) 分发。

运行时产生的文件（不在本目录）：

- 配置：`%APPDATA%\MinBirdPet\config.json`（位置、尺寸、散步开关、窗口行走开关、待机动画开关）
- 日志：`%APPDATA%\MinBirdPet\minbird_pet.log`（加 `--debug` 启动时写入）

## 四、命令行参数

```
MinBirdPet.exe --size 232        指定初始高度（像素），默认 168
MinBirdPet.exe --no-walk         不要自己散步
MinBirdPet.exe --static          本次启动先关掉待机动画（右键菜单里可再打开）
MinBirdPet.exe --debug           写运行日志，便于排错
MinBirdPet.exe --selftest        只渲染一张姿态预览图，不开窗口
```

## 五、想改成别的图？

1. 把你的图抠成透明底 PNG（4 MB 以内），命名成 `assets\minbird.png`；
2. 用仓库里的 spec 直接打包（推荐），或用等价命令行：

```bat
pip install -r requirements-dev.txt
pyinstaller --noconfirm MinBirdPet.spec
```

等价的命令行写法：

```bat
pyinstaller --noconfirm --onefile --windowed --name MinBirdPet ^
  --icon assets\minbird.ico --add-data "assets;assets" minbird_pet.py
```

## 六、也可以直接把这张图丢给现成的桌宠项目

抠好的透明底 PNG 可以通用，下面是调研过的几个项目（详见对话中的对比）：

- **WindowPet**（Tauri/React）：内置商店 + "Add your own custom pet"，自带点击穿透、开机自启。
  <https://github.com/SeakMengs/WindowPet>
- **dingzd1995/desktop-pet**（Tauri 2/React）：支持"导入本地图片"，有 sakana-widget 那种甩动惯性。
  导入的图片放在 `%APPDATA%\com.dingzd.desktoppet\pets\`。
  <https://github.com/dingzd1995/desktop-pet>
- **wjunbin/desktop_pat**（Python/PySide6）：直接导入 PNG/JPG/GIF/APNG，可漫游、可画"热点"。
  <https://github.com/wjunbin/desktop_pat>
- **VPet**：最老牌，但走的是序列帧 MOD 路线，一张静态图没法直接用。
  <https://github.com/LorisYounger/VPet>

## 七、给它接上「余额」和「天气」

右键菜单 → **设置**，在设置窗口里填 Key、城市、调开关，点「保存」即时生效（不用重启）。
也可以直接改配置文件（珉鸟每 2 秒自动重读）：

```
%APPDATA%\MinBirdPet\config.json
```

### 1. DeepSeek 余额

在设置窗口（或配置文件 `deepseek_api_key` 字段）里填你的 key，**保存即可，不用重启** —— 珉鸟每 2 秒会看一眼配置文件，
发现变了就自动重新读取，还会说一句「配置更新啦」。

```json
{
  "deepseek_api_key": "sk-你的key",
  "city": "济南"
}
```

然后右键 →「看看 DeepSeek 余额」，珉鸟头顶会显示：

```
DeepSeek 余额
余额 ¥9.98
充值 ¥9.98 · 赠送 ¥0.00
快见底了，该充值了
```

- Key 从 <https://platform.deepseek.com/api_keys> 拿。
- **Key 只存在你本机这个文件里**，代码和 exe 里都没有硬编码，也不会传到任何第三方。
- 走的是官方接口 `GET https://api.deepseek.com/user/balance`。
- 低于 5 元珉鸟会多嘴提醒一句。

### 2. 「每花满 N 元提醒我」

右键菜单里有两项：

```
余额提醒：每 ¥1（点击切换）     ← ¥1 → ¥5 → ¥10 → 关，循环切换
自动查余额：未开启（点击切换）   ← 开 = 交给 Windows 计划任务，每小时查一次
```

**台阶是累计的，不是每次差额。** 花 0.4 元不吭声，再花 0.7 元凑满 1 元才喊你；
一次花掉 3.7 元就报「又花掉 ¥3」，剩的 0.7 留着跟下一次累计。充值时珉鸟会说「充值 +¥X」。

**默认不会有任何后台请求。** 珉鸟只在三个时刻查余额：

| 时机 | 说明 |
| --- | --- |
| 你点「看看 DeepSeek 余额」 | 弹完整余额 |
| 珉鸟启动 5 秒后 | 静默查一次，没跨台阶就一个字都不说 |
| 计划任务每小时唤起一次 | 见下 |

**关于「不要再后台一直连着查」** —— 设计上珉鸟主进程里没有任何周期性联网代码。
要自动提醒，走的是 Windows 计划任务：系统每小时唤起一次 `MinBirdPet.exe --check-balance`，
这个进程**查一次 API、算完台阶就退出**，不留后台。结果写进 `%APPDATA%\MinBirdPet\alerts.jsonl`，
珉鸟在已有的本地文件轮询里顺手取走并弹气泡（本地磁盘读取，不是网络请求）。

开关方式二选一：

- **点菜单「自动查余额」**（推荐）→ 内部调 `schtasks` 注册/删除计划任务。
  少数机器会因安全策略拦 `schtasks.exe`，这时珉鸟会明确说「设置失败」，用下面的方法。
- **手动注册**，管理员或普通权限都行，在 PowerShell 里跑：

  ```powershell
  $exe = "C:\路径\MinBirdPet.exe"
  schtasks /create /tn "MinBirdPet-BalanceCheck" /tr "`"$exe`" --check-balance" /sc hourly /mo 1 /f
  ```

  想改成每 2 小时就把 `/mo 1` 换成 `/mo 2`。删掉：`schtasks /delete /tn "MinBirdPet-BalanceCheck" /f`。

- **兜底**：如果计划任务怎么都开不起来，在 `config.json` 里加一行
  `"balance_check_minutes": 60`（多少分钟查一次）。这是让珉鸟自己定时查，
  会留下周期性请求，所以默认 `0` = 关。

相关配置字段（缺失时珉鸟会自动补默认值）：

```json
{
  "balance_step": 1.0,             // 每花满多少元提醒一次；0 = 关
  "balance_baseline": null,        // 提醒基准，第一次查到余额时自动建立
  "balance_check_on_start": true,  // 启动时静默查一次
  "balance_check_minutes": 0       // 珉鸟自己定时查的间隔；0 = 不查
}
```

### 3. 今天天气

`city` 填中文城市名（`济南`、`上海`、`山东济南` 都行）。**留空也行** —— 第一次点「今天天气怎么样」时，
珉鸟会用 IP 粗定位猜你的城市，并自动写回配置，之后就一直用它。

```
山东济南 · 晴间少云 30°
湿度29% 风12km/h
今日 21°~30° 阴 雨2%
明日 21°~32° 阴
紫外线 6（强）
天气不错，出去走走？
```

天气数据来自 [Open-Meteo](https://open-meteo.com/)，**免费、不用注册、不用 key**。

### 4. 查不到怎么办

| 珉鸟说 | 原因 |
| --- | --- |
| `还没填 API Key` | `deepseek_api_key` 是空的；填完保存等两秒让珉鸟重读 |
| `配置文件读不懂啦` | JSON 写坏了（多半是逗号/引号问题）。此时珉鸟会**停止写配置**以免冲掉你的内容，修好格式即可 |
| `API Key 不对（401）` | key 写错了 / 有多余空格 / 已失效 |
| `余额不足（402）` | 官方明确说余额不够调用了 |
| `网络连不上：...` | 断网，或接口被墙/超时 |

## 八、实现要点

- **逐像素透明**：`CreateWindowExW` 建 `WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE` 的
  无边框窗口，每帧用 Pillow 合成 RGBA，预乘 alpha 后经 `UpdateLayeredWindow` 推上去 —— 所以发丝边缘
  是半透明的，没有"锯齿白边"。
- **点击穿透**：处理 `WM_NCHITTEST`，取当前帧的 alpha 通道做判定，透明像素返回 `HTTRANSPARENT`。
- **DPI**：启动即 `SetProcessDPIAware()`，在 150% 缩放的屏幕上位置和尺寸才不会错位。
- **能站在窗口上**：每秒枚举一次可见的应用窗口（滤掉工具窗、点击穿透层、挂起的 UWP、
  桌面和任务栏），用 DWM 扩展边界取真实可见的标题栏位置；鸟脚点落在哪扇窗口里就站谁的顶边，
  走出边沿、窗口被拖走或关掉都会掉下去，窗口慢慢拖动时鸟会跟着窗沿走。
- **序列帧待机动画**：待机时的呼吸、眨眼、歪头来自绿幕 AI 视频的切帧
  （`tools/make_seq.py` 一条龙：去水印 → 色键抠像 → 无缝循环搜索 → spritesheet），
  运行时按 24 fps 循环播放；拖拽甩动、抛掷弹跳的物理变形仍由程序实时叠加在当前帧上。
  右键菜单「待机动画」可随时切换静态/动态（选择记在配置 `seq_anim` 里），
  删掉 `assets/seq/` 或加 `--static` 也能回到静态图模式。
- **CPU**：30 fps，单帧合成约 4–7 ms（不同尺寸），托盘常驻、无界面时不占资源。

## 九、参考与致谢

动工之前调研了下面这些开源桌宠项目，对比了它们对「导入自定义图片」的支持方式和交互设计，
最终为了「零安装、单文件、直接用这张图」选择自己实现。珉鸟的全部代码为独立编写
（Python + ctypes 调 Win32 分层窗口），未复制上述项目的代码，在此致谢：

| 项目 | 技术栈 | 说明 |
| --- | --- | --- |
| [SeakMengs/WindowPet](https://github.com/SeakMengs/WindowPet) | Tauri + React | 宠物在窗口上行走、点击穿透、开机自启 |
| [dingzd1995/desktop-pet](https://github.com/dingzd1995/desktop-pet) | Tauri 2 + React | 支持导入本地图片，甩动惯性交互 |
| [wjunbin/desktop_pat](https://github.com/wjunbin/desktop_pat) | Python + PySide6 | 直接导入 PNG/JPG/GIF/APNG，可漫游、画热点 |
| [LorisYounger/VPet](https://github.com/LorisYounger/VPet) | C# + WPF | 老牌桌宠，序列帧 MOD 生态 |

另外感谢：

- [Open-Meteo](https://open-meteo.com/) —— 免费无 key 的天气接口；
- [DeepSeek](https://platform.deepseek.com/) —— 余额查询走官方接口。

## 十、许可证

代码部分以 [MIT License](LICENSE) 开源。

`assets/` 里的珉鸟图片基于 aespa 成员 Karina（柳智敏）的粉丝表情包二次加工，**仅供参考与个人娱乐的非商业用途**，形象版权归原作者及相关权利人所有，不随 MIT 许可证授权。若有侵权，请联系移除。
