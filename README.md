# 魔兽争霸3重制版改键工具构建源码

本项目只收录独立改键软件的构建输入及直接相关的验证文件，不包含修改器、单位选择工具、混合源码快照、诊断日志、逆向资料、游戏文件、用户数据或部署配置。

当前源码：**2.0.1**，自动选择 Warcraft III **3.0.0.24268 / 3.0.1.24323 / 3.0.1.24371** 的独立适配。

- [当前版本完整构建步骤](HOTKEY_BUILD.md)
- [历史改键版本与构建说明](VERSION_SOURCE_MAP.md)
- [EXE 发布](https://github.com/dc114154qq/war3-reforged-tools-source/releases/tag/hotkeys-v2.0.1)
- [个人网站](https://twomengxi.xyz/hotkeys/)

原生 DLL 从 C 源码生成，EXE/DLL 只作为本地构建输出或 Release 附件，不提交到 Git 源码树。
`.gitignore` 对源码输入使用白名单；新增构建依赖必须同时更新白名单，重新验证从干净源码构建。
历史目录保留对应旧版的运行源码和打包配置，不拿当前代码冒充历史版本。
