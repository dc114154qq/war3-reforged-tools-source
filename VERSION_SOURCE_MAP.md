# 改键软件版本源码

这些是改键工具版本，不是修改器版本，也不是游戏版本。

| 改键工具版本 | 源码目录 | 构建方式 |
| --- | --- | --- |
| 1.0.0 | `versions/hotkeys-v1.0.0/` | 在该目录执行 `python tools/build_hotkeys.py` |
| 1.0.1 | `versions/hotkeys-v1.0.1/` | 在该目录执行 `python tools/build_hotkeys.py` |
| 2.0.0 | 仓库根目录及 `versions/hotkeys-v2.0.0/` | 在对应目录执行 `python tools/build_war3_hotkeys.py` |

Windows x64、Python 3.12、LLVM Clang、MSVC/Windows SDK 是构建前提。先安装根目录 `requirements-hotkeys.txt`。
旧版源码及 spec 与原存档保持一致；为 1.0.0/1.0.1 补充的构建脚本仅把 helper 编译及 PyInstaller 命令串起来。
1.x 输出 `dist/War3ReforgedHotkeys.exe`，2.0.0 输出 `dist/War3ReforgedHotkeys-v2.0.0.exe`。
旧版构建成功不等于可用于当前 3.x 游戏，不将旧版本宣称为新游戏适配。

本次仅清理发布范围，不修改软件功能或替换用户已经验证的 EXE；旧混合源码仍保存在本地原仓库。
