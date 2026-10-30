# LATX CPU 兼容运行

PatchDock、Cyndi、iFitDock 的现有核心为 x86 程序，使用 LATX 在龙芯 CPU 上执行。这不是原工具的龙芯原生重编译，也不使用 SDAA 代替 CPU 搜索。

源码与构建依赖身份见 [latx-source.json](../../locks/latx-source.json)、[meson-wheel.json](../../locks/meson-wheel.json)，已准备运行包的哈希见 [latx-runtime.json](../../locks/latx-runtime.json)。

`build.sh SOURCE NEW_BUILD 64|32` 整理自实际 configure／ninja 命令，需要已有编译依赖和 `MESON` 包装器。此封装入口未重新完成一次独立全量编译；现有验证使用已锁定的外部运行包。

x86 sysroot、原工具、编译产物及其许可分别管理，不随源码目录自动提供。更换运行包后应核对哈希并重做相应工具固定输入验收。计时包含 CPU、翻译器和启动成本，不解释为纯翻译开销。
