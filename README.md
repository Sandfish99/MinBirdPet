# 珉鸟桌宠 / MinBird Desktop Pet

![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-0078D6)
![Release](https://img.shields.io/github/v/release/Sandfish99/MinBirdPet)
![License](https://img.shields.io/badge/license-MIT-green)

把「珉鸟」变成住在 Windows 桌面上的桌宠 —— 逐像素透明、点击穿透、
还会站到别的窗口标题栏上散步。

![珉鸟](assets/_preview_light.png)

## ✨ 功能

- 🐦 **单文件桌宠** —— 下载即用，免安装、免管理员权限
- 🚶 **会动的珉鸟** —— 呼吸/眨眼/歪头待机动画，拖拽甩动、抛掷弹跳
- 🪟 **窗口行走** —— 能跳上应用窗口的标题栏散步，窗口关了会掉下来
- 🍅 **番茄钟** —— 菜单一键开始，专注/短休/长休循环，气泡提醒
- 💰 **DeepSeek 余额** —— 头顶显示余额，花满 N 元喊你一次
- 🌤 **天气** —— 今天天气 + 明日预报（Open-Meteo，免 key）
- 🎵 **aespa 联动** —— 放 aespa 的歌，珉鸟跟着摇摆蹦跶
- ⚙️ **设置中心** —— 搜索式设置界面，全部即时生效

## 📦 下载

从 [Releases](https://github.com/Sandfish99/MinBirdPet/releases/latest) 下载
`MinBirdPet.exe`，放到任意目录双击即可。

更多细节（命令行参数、DeepSeek 配置、休眠恢复、实现原理）见
[详细文档](docs/USAGE.md)。

## 🛠 构建

```bat
pip install -r requirements-dev.txt
pyinstaller --noconfirm MinBirdPet.spec
```

## 📄 License

代码以 [MIT](LICENSE) 开源；珉鸟形象为粉丝二创，版权归原作者。
第三方组件声明见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。
