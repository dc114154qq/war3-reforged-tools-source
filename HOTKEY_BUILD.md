# 改键工具 2.0.1 源码构建

此版本是独立改键工具，不是修改器。适配包按游戏 PE 构建指纹自动区分 `3.0.0.24268`、`3.0.1.24323` 与 `3.0.1.24371`；未知 3.x 构建不沿用旧地址。

构建需要 Windows x64、Python 3.12、LLVM Clang，以及可供 Clang 使用的 Windows SDK/MSVC x64 链接工具。Python 依赖见 `requirements-hotkeys.txt`。

在仓库根目录执行：

```powershell
python -m pip install -r requirements-hotkeys.txt
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
python -m pytest -q test_war3_hotkey_tool.py test_hotkey_adapters.py test_hotkey_window_icon.py test_hotkey_readiness.py test_hotkey_24371.py
python tools/build_war3_hotkeys.py
```

输出为 `dist/War3ReforgedHotkeys-v2.0.1.exe`。构建脚本从已提交 C 源码生成旧版 helper 和三份独立 3.x 桥 DLL；版本头文件从对应 JSON 生成。`.spec` 明确收集 Capstone 的 `capstone/lib/capstone.dll` 和高清 PNG，避免出现源码可运行而 EXE 缺依赖的情况。

仅编译原生依赖：

```powershell
python tools/build_war3_hotkeys.py --native-only
python tools/build_war3_hotkey_bridge.py --game-version 3.0.0.24268 --check-header
python tools/build_war3_hotkey_bridge.py --game-version 3.0.1.24323 --check-header
python tools/build_war3_hotkey_bridge.py --game-version 3.0.1.24371 --check-header
```

连接、对局检测及配置应用不依赖游戏在前台；实际键鼠输入仍受前台、聊天和暂停开关约束。运行时状态保存在 `%APPDATA%/Twomengxi/War3ReforgedHotkeys/runtime-status.json`，该文件及用户配置不应提交到仓库。

构建验证应区分原生表读回和实际按键效果。`--self-test-engine` 只验证输入引擎启动；对局初始化和 12 格配置读回可用下面的命令核对，PID 必须替换为当前实际目标：

```powershell
dist/War3ReforgedHotkeys-v2.0.1.exe --self-test-native --expected-game-pid 12345 --diagnostic-output build/native-check.json
```

2026-10-02 交付包完成 77 项自动测试、打包后的初始化及读回验证，用户随后报告实际使用可用。3.0.0 配置保持原有独立适配；本次用户实测的游戏为 3.0.1.24323。不据此宣称其他构建或所有外机均已实测。

本仓库只保存构建代码、版本数据、测试及必要图标。EXE 下载由本项目 GitHub Release 和个人网站提供；不包含游戏文件、日志、内存数据、逆向资料或部署凭据。

2026-11-16：2.0.1 最小新增 24371 JSON、生成头文件、独立 DLL 和版本选路／构建入口；界面、配置、输入规则及原两套适配数据不变。272 项离线回归通过，原两套桥的 `.text` 与旧发布包一致。先前测试构建已在 3.0.1.24371 上完成临时键位改变／恢复、生产初始化、12 格键位读回及原键位／模式恢复。正式版按用户要求只追加代码、版本资源和打包核验，不重复操作游戏；实际物理按键效果和外机兼容仍未验收。
