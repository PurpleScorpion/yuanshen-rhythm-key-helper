# 原神 · 千音雅集助手

<img src="assets/logo.png" alt="原神 · 千音雅集助手图标" width="88">

适用于 Windows 10/11 x64 的《原神》「千音雅集」六轨音游助手。程序从游戏窗口画面跟踪 A、S、D、J、K、L 六条轨道。黄色圆点到达判定线时短按，紫色长条起点到线时按住，终点到线时松开。桌面窗口提供校准教程、自定义快捷键和运行日志。

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

## 校准和演奏

1. **练习选点。** 点击主窗口的 **校准教程**。先点 A 字母上方最左边的白色判定圆中心，再点 L 字母上方最右边的白圆。确认绿色预览线穿过六个圆心后，点击 **确认保存** 或按 Enter。选错可点 **重选**。练习结果写入单独的 `calibration-practice.json`。
2. **对准游戏。** 进入原神的六轨音游界面，点击 **游戏校准** 或按校准快捷键（默认 F6）。在游戏截图上选择同样的两个圆心。正式校准保存到 `config.json`。如果独占全屏遮住校准窗口，可以用 Alt+Tab 切换，或将游戏设为无边框窗口。
3. **开始演奏。** 在音符出现前点击 **开始演奏**，或在游戏中按启停快捷键。默认使用开启 Num Lock 后的小键盘 9。看到“等待原神”时切回游戏，窗口稳定后助手会开始识别。
4. **停止或退出。** 再按一次启停快捷键或点击 **停止演奏**。切出游戏、改变游戏窗口位置或尺寸时，助手会暂停并松开持有的键。关闭主窗口即可退出。

主窗口和游戏内状态条会显示待启动、等待、运行或错误等状态。运行日志记录识别 FPS 和已发送的按键。命中时机受下落速度、截图帧率、显示设置以及游戏是否接受模拟输入影响。

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

这些命令可用于仅识别模式、校准练习和离线检查。最后一条读取本地游戏截图，在同目录生成标注图。

```powershell
.\.venv\Scripts\python.exe main.py --dry-run
.\.venv\Scripts\python.exe main.py --calibration-demo
.\.venv\Scripts\python.exe main.py --inspect .\game.png --output .\inspection.png
```

## 构建便携版

在 Windows x64 上运行 [build.ps1](build.ps1)。构建已在 CPython 3.13 x64 上验证，所选 Python 需要包含 Tcl/Tk。脚本使用虚拟环境安装 [构建依赖](requirements-build.txt)，生成独立的 Windows GUI 程序，检查图标、Tcl/Tk 资源、管理员清单和压缩包完整性。

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
