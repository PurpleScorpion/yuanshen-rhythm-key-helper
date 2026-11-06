# 原神 · 千音雅集助手

<img src="assets/logo.png" alt="千音雅集道具图标" width="88" align="right">

这是一个适用于 Windows 10/11 x64 的《原神》「千音雅集」六轨音游助手。它识别 A、S、D、J、K、L 六条轨道上的音符：黄色圆点到达判定线时短按，紫色长条到线时按住，尾端到线时松开。

## 作者声明

1. **本程序仅供学习和交流使用，严禁用于商业用途。**
2. **为了游戏平衡，游戏内严禁在「传说模式」使用本程序，否则后果自负。**（传说模式会随机故意按错几个键。）
3. 游戏中请使用「垂直模式」。界面样式请选择初始版本的「轻漾涟漪」，请勿使用其他购买的样式。
4. 在游戏的「设置 → 特化」中，四个选项均请留空，包括降低难度的选项。（做这个的时候压根就没看到有这个功能。）

开源项目见 [GitHub 上的 yuanshen-rhythm-key-helper](https://github.com/PurpleScorpion/yuanshen-rhythm-key-helper)。

## 使用教程

### 1. 解压并启动

**[下载 v0.9 Windows 64 位完整包（65.73 MiB）](https://github.com/PurpleScorpion/yuanshen-rhythm-key-helper/raw/refs/heads/main/%E8%BD%AF%E4%BB%B6%E4%B8%8B%E8%BD%BD/yuanshen-rhythm-key-helper-windows-x64.zip)**

1. 将便携包 `yuanshen-rhythm-key-helper-windows-x64.zip` **完整解压**到一个可写文件夹，例如 `D:\游戏工具\千音雅集助手\`。已实测从含中文和空格的目录启动，主窗口可以正常打开和关闭。
2. 打开解压后的 `yuanshen-rhythm-key-helper` 文件夹，双击 **`yuanshen-rhythm-key-helper.exe`**。Windows 弹出管理员授权提示时选择「是」。便携版自带 Python 和运行依赖，请保留 EXE 旁边的 `_internal` 文件夹。
3. 首次启动会显示「使用声明」。阅读后点击 **我接受** 进入助手。选择退出或关闭声明窗口，程序就会退出，下次启动仍会显示声明。接受记录保存在当前 Windows 用户的本机目录；使用同一账户重新启动或移动程序后会直接进入主窗口。随时点击主窗口的 **使用声明** 即可再次查看。
4. 如果你下载的是 GitHub **Code → Download ZIP**，先解压整个仓库，再到 `软件下载` 文件夹里找到便携包，按第 1 步解压。开发者也可[从源码运行](#从源码运行)或自行[构建便携版](#构建便携版)。

本次首次发布提供 v0.9 完整包。后续版本的增量更新会放在[更新包目录](./软件下载/更新包/)。

### 2. 第一次使用时校准

- **先练习。** 点击主窗口的 **校准教程**，没有原神也可以试。跟着提示点击 A 字母上方最左侧白圆的中心，再点 L 字母上方最右侧白圆的中心。绿色预览线应穿过六个判定圆。点击 **确认保存** 或按 Enter，点错可点 **重选**。教程结果单独保存在 `calibration-practice.json`。
- **再校准游戏。** 进入游戏的六轨演奏界面，按 **F6**（默认）或点击 **游戏校准**。在游戏截图上按同样的方法选 A、L 两个圆心并保存。如果全屏遮住校准窗口，可用 Alt+Tab 切到助手。正式校准写入 EXE 旁的 `config.json`，关机重启后会自动加载；分辨率或界面布局变化时可重新校准。

### 3. 开始和停止演奏

在音符出现前，点击 **开始演奏**，或在游戏中按默认启停键 **小键盘 9**（开启 Num Lock）。看到「等待原神」时切回游戏，状态变成「运行中」后开始识别。**没有小键盘**时，先在[快捷键设置](#快捷键和日志)里把启停键改成 F8 或 Ctrl+F8。

再次按启停键或点击 **停止演奏** 即可停止。切出游戏、移动游戏窗口或改变窗口尺寸时，助手会暂停并松开按键。关闭主窗口即可退出。

## 编程语言和图像识别技术

助手使用 **Python** 开发，桌面界面使用 **Tkinter**。识别和按键过程分为三步：

1. **截图与颜色识别。** MSS 连续截取判定线附近的画面，NumPy 提供像素数组。OpenCV 将每条轨道的图像转为 HSV，按色相、饱和度和亮度筛出黄色和紫色区域。
2. **形状与长条识别。** OpenCV 用形态学处理连接小缺口，再提取轮廓，根据大小、圆度和轨道位置筛选音符。紫色圆圈上方或下方连接的长条，用来区分长按起点和终点。
3. **到线与按键。** 程序对比连续多帧的音符位置，估算下落速度和到线时间，再通过 Windows `SendInput` 发出对应的按下和松开动作。

## 从源码运行

1. 安装 64 位 CPython 3.12、3.13 或 3.14，安装时保留 pip、venv 和 Tcl/Tk。推荐使用带 Python launcher 的 Windows 安装程序。
2. 下载源码并解压到可写文件夹。双击 `start.cmd` 打开助手。初次启动会创建本地 `.venv`，并联网安装依赖。也可以先运行 `setup.cmd` 单独完成安装。
3. 助手启动后先待命。点击 **校准教程** 可以在没有游戏的情况下练习选点。只想查看识别结果时，可以运行 `preview.cmd` 进入仅识别模式。

以下 PowerShell 命令均在源码根目录执行。首次创建环境时，可以向安装脚本指定本机的 Python 路径。例如选择已安装的 3.13：

```powershell
$pythonPath = py -3.13 -c "import sys; print(sys.executable)"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Python $pythonPath
.\start.cmd
```

换电脑时重新创建本地虚拟环境。如果脚本发现旧的 `.venv` 已失效，会先将它备份为 `.venv.backup-*`，再使用本机 Python 重建。游戏以管理员权限运行时，源码版也需要以相同权限启动才能发送按键。

## 快捷键和日志

在 **快捷键设置** 中，点击 **启停演奏** 或 **游戏校准** 旁的键位，按下新键，再点击 **应用**。没有数字小键盘时，可以使用 F8 或 Ctrl+F8。单键可用 F1 至 F11 或小键盘数字，主键区字母和数字需搭配 Ctrl、Alt 或 Shift。两个动作需要使用不同按键。

如果新组合已被其他程序占用，助手会提示冲突并保留原有绑定。初次启动时已有快捷键被占用，也可以从主窗口更换键位。点击 **恢复默认** 再 **应用**，即可恢复小键盘 9 和 F6。成功保存后，重启会沿用这些设置。

在 **近期动作与日志** 内可以用滚轮翻阅，或拖动右侧滑块查看历史记录。回到底部会继续跟随新日志。选中文字后按 Ctrl+C 可复制。诊断日志位于配置文件同目录的 `logs/rhythm.log`，单份约 2 MB，最多保留当前文件和两个备份。

## 配置和调试

默认配置见 [config.example.json](config.example.json)。没有 `config.json` 时，程序直接使用内建默认值。保存正式校准或应用快捷键后会创建本机配置。手动调整时先退出助手，可以从示例复制一份为 `config.json` 后编辑。

| 设置 | 默认 | 用途 |
| --- | --- | --- |
| `input_lead_ms` | 8 ms | 正数提前输入，负数延后输入。整体偏晚时可以每次增加约 5 ms。 |
| `tap_ms` | 28 ms | 黄色音符短按的持续时间。 |
| `max_hold_seconds` | 30 秒 | 单次长按的最长持续时间。 |
| `target_fps` | 120 | 截图识别的目标帧率，实际速度取决于电脑性能。 |
| `lane_x`、`hit_y` | 默认六轨位置 | 相对于游戏客户区宽高的坐标，优先使用游戏校准设置。 |
| `hotkeys.toggle`、`hotkeys.calibrate` | `NumPad9`、`F6` | 系统全局启停和校准快捷键。 |

这些命令可用于仅识别模式、校准练习和离线检查。最后一条读取本地游戏截图，在同目录生成标注图。首次离线检查前请先启动助手并接受使用声明。

```powershell
.\.venv\Scripts\python.exe main.py --dry-run
.\.venv\Scripts\python.exe main.py --calibration-demo
.\.venv\Scripts\python.exe main.py --inspect .\game.png --output .\inspection.png
```

## 构建便携版

在 Windows x64 上运行 [build.ps1](build.ps1)。构建使用 CPython 3.13 x64，所选 Python 需要包含 Tcl/Tk。脚本使用虚拟环境安装 [构建依赖](requirements-build.txt)，生成独立的 Windows GUI 程序，检查图标、Tcl/Tk 资源、管理员清单和压缩包完整性。Windows 启用旧路径长度限制时，请将源码放在较短的目录中。如果构建报告 WinError 206，缩短源码和输出目录后重试。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
```

成功后可直接运行 `dist\yuanshen-rhythm-key-helper\yuanshen-rhythm-key-helper.exe`，或将 `dist\yuanshen-rhythm-key-helper-windows-x64.zip` 复制到另一台 Windows 电脑。使用者需要完整解压 ZIP。运行库在 EXE 旁的 `_internal` 文件夹内。Windows 打开程序时会请求管理员授权。

如需复用已有的构建虚拟环境，可以给 `-Python` 提供其中的 `Scripts\python.exe`。指定基础 Python 时，脚本会在本次 `build\` 工作目录中创建独立的构建环境。再次构建时可用 `-OutputDir` 指定新的输出目录。每份便携包都从 `config.example.json` 初始化默认配置。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 -Python .\.venv\Scripts\python.exe -OutputDir .\dist-local
```

便携版的使用说明见 [PORTABLE-README.txt](PORTABLE-README.txt)。

## 开发检查

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
```
