# 第三方组件声明

本仓库自身以 GPL-3.0-or-later 发布。以下第三方组件随仓库分发或以外部依赖方式使用。

## 随仓库分发

### unrpa —— GPL-3.0

- 位置：`vendor/unrpa/`
- 版本：2.3.0
- 来源：https://github.com/Lattyware/unrpa
- 用途：解包 Ren'Py 的 `.rpa` 资源归档。
- 许可：GNU GPL v3.0（全文见 `vendor/unrpa/LICENSE`；各源文件头部保留原版权声明）。
  该组件是 GPL 许可，本仓库整体因此采用 GPL-3.0-or-later。

### unrpyc (目录名 `vendor/unren/`) —— MIT

- 位置：`vendor/unren/`
- 版本：v2.0.3
- 来源：https://github.com/CensoredUsername/unrpyc
- 用途：把已编译脚本 `.rpyc` 反编译回 `.rpy`。
- 许可：MIT（全文见 `vendor/unren/LICENSE`）。
- 版权：Copyright (c) 2012-2024 Yuri K. Schlesner, CensoredUsername, Jackmcbarn。

## 外部依赖（不随仓库分发）

### projz_renpy_translation —— GPL-3.0

- 用途：翻译引擎本体（索引、导出、回填、注入）。
- 来源：https://github.com/abse4411/projz_renpy_translation
- 获取方式：由 `安装.bat` 在首次运行时 clone 到仓库的平级目录；**本仓库不包含它的代码**。
- 许可：GPL-3.0（见其仓库内 `LICENSE`）。
- 许可全文见本仓库根目录的 `LICENSE`（与引擎一致，均为标准 GPLv3）。

### 引擎的 Python 依赖

`安装.bat` 会按引擎仓库的 `requirements.txt` 从其官方发布渠道安装
（PyQt5、selenium、pandas、numpy 等约 60 个包）。这些包各自遵循其自身许可，
不随本仓库分发。

## 文档中提到的第三方翻译方法论

`翻译提示词.md` 与 `docs/` 中的方法论汇编自公开资料，均为 MIT 许可的社区技能
（英译汉润色、Ren'Py 本地化管线、视觉小说全流程、精翻四步法、中文去模板化清单），
**仅作文字指导使用，其代码不随本仓库分发**。若你的环境未安装这些技能，
提示词本身仍然自足可用。
