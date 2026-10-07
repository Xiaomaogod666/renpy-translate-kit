# RenPy 翻译工具包 (renpy_translate_kit)

把 Ren'Py 游戏拖进来，就能导出全部未翻译文本、交给任意翻译手段（AI 对话、翻译网站）、
再把译文装回游戏的一套 Windows 工具。

它是 [`projz_renpy_translation`](https://github.com/abse4411/projz_renpy_translation)
（下称"引擎"）外面的一层简化外壳：引擎负责解包、索引与回填，本工具包负责
"把游戏目录拖到 `.bat` 上就完事"——不需要敲命令行、不需要读引擎的手册。

## 能做什么

- **自动解包**：游戏还是 `.rpa` / 只有 `.rpyc` 时自动解开（内置 unrpa + unrpyc）。
  非标准打包（`.rpa` 条目不带 `game/` 前缀）也能正确解进 `game/`，见
  [ADR 0006](docs/adr/0006-rpa-without-game-prefix.md)。
- **导出**：把该游戏该语言**全部未翻译的行**导出成 JSON（`tid → 原文`）。
- **回填**：把填好译文的 JSON 拖回来，写入索引并生成游戏可加载的翻译文件。
  分了多个 part 的翻译只拖其中一个，同目录的其余 part 自动组队一次装回
  （见 [ADR 0007](docs/adr/0007-part-queue-apply.md)）。
- **中文显示支持**：注入语言/字体切换插件，让中文不显示成方块。
- **译文自检**：`check_translation.py` 比对原文与译文，预判会让游戏对不上号的行。
- **一键还原**：撤掉工具装进游戏的所有东西。
- **关第三方汉化钩子**：清掉某些汉化包塞在剧本里的在线翻译注入（可预览、有备份）。

## 目录结构

```
某文件夹\
├── renpy_translate_kit\          <- 本仓库，拖拽工具
│   ├── 安装.bat                  <- 第一次运行：取引擎 + 建虚拟环境 + 装依赖
│   ├── 翻译.bat                  <- 拖游戏目录 = 导出 / 拖 JSON = 回填
│   ├── 去掉汉化.bat              <- 撤掉本工具装进游戏的东西
│   ├── 关掉第三方汉化.bat        <- 清掉第三方汉化包的注入（可选）
│   ├── kit.py / untranslate.py / unhook.py / check_translation.py
│   ├── 翻译提示词.md             <- 交给 AI 对话的翻译说明
│   ├── 使用说明.md               <- 面向使用者的完整中文说明
│   ├── docs\                     <- 术语表、ADR、翻译腔对照示例
│   └── vendor\                   <- unrpa / unrpyc（解包用的第三方组件）
├── projz_renpy_translation\      <- 引擎，由 安装.bat 自动获取
└── workspace\                    <- 每个游戏一个子目录：导出文件、进度、备份
```

`workspace` 刻意放在两个工具目录**之外**：升级或替换工具目录不会带走翻译进度。

## 安装

需求：Windows、[Python 3.9–3.11](https://www.python.org/downloads/)（推荐 3.11，
安装时勾选 "Add python.exe to PATH"）、[Git](https://git-scm.com/download/win)。

> 引擎锁定了 PyQt5 5.15.9、numpy 1.24.4 等一批依赖，它们没有 Python 3.12+ 的预编译包，
> 用 3.12 及以上会在装依赖那一步失败。`安装.bat` 会优先挑 3.11，挑不到再往下退。

1. 下载/克隆本仓库到任意文件夹。
2. 双击 `安装.bat`。它会：
   - 把引擎 clone 到 `..\projz_renpy_translation`（浅克隆，仅首次）；
     `git` 不在或 clone 不通时，改用 `fetch_engine.py` 走 https 直接下 zip
     （下载中断会自动重试）。
   - 在引擎目录里建 `.venv` 虚拟环境；
   - `pip install -r requirements.txt`（约 60 个包，PyQt5 等，首次需要几分钟）。
     若 pip 报证书错（公司代理、抓包代理、镜像站的证书链都可能触发），
     脚本会自动用官方 bootstrap 把 pip 换成新版再重试一次。
3. 完成后即可使用。

> **网络不通/装不上依赖时**，可用的开关（设成环境变量后重跑 `安装.bat`）：
>
> | 变量 | 用途 |
> |---|---|
> | `KIT_PIP_INDEX` | pip 镜像，如 `https://pypi.tuna.tsinghua.edu.cn/simple` |
> | `KIT_ENGINE_REPO` | 换成自建/镜像的引擎仓库地址 |
> | `KIT_ENGINE_ZIP` | 引擎 zip 的直链，或本地 zip 路径 |
> | `KIT_PYTHON` | 指定用哪个 `python.exe` 建环境 |
>
> 还可以手动把引擎 zip 和 `get-pip.py` 下好，再分别喂给
> `fetch_engine.py <目标目录> <zip>` 与 `fetch_pip.py <venv目录> <get-pip.py>`。

> 已经有装好的引擎？把 `projz_renpy_translation`（含 `.venv`）放在与本目录平级的位置，
> 跳过 `安装.bat` 即可。
> 环境不在默认位置时，可以设环境变量 `KIT_PYTHON` 指向任意 `python.exe`。

## 使用

1. **导出**：把游戏目录（含 `.exe` 的那一层）拖到 `翻译.bat` 上。
   首次会启动游戏一次让它报出文本清单（窗口自动关闭），随后生成
   `workspace\{游戏名}\待翻译\{游戏名}_schinese_001.json`。
2. **翻译**：把 JSON 交给 AI 对话或翻译网站。推荐连同 `翻译提示词.md` 第一段一起发。
3. **自检（建议）**：
   ```
   <引擎目录>\.venv\Scripts\python.exe check_translation.py 原文.json 译文.json
   ```
   报错的行必须修，提示的行逐条看一眼。
4. **回填**：把译文 JSON 拖到 `翻译.bat` 上；进游戏按 **Ctrl + I** 选"简体中文"。
5. **还原**：把游戏目录拖到 `去掉汉化.bat` 上（先加 `-n` 可只预览清单）。

详细步骤、常见问题见 [`使用说明.md`](使用说明.md)。

## 配置

编辑 `kit.json`：

| 键 | 默认 | 说明 |
|---|---|---|
| `tool_dir` | `../projz_renpy_translation` | 引擎位置（相对本目录） |
| `workspace` | `../workspace` | 工作区位置（相对本目录） |
| `target_language` | `schinese` | 目标语言 |
| `export_limit` | `0` | 每次导出上限；`0` = 全部 |
| `open_folder_after_export` | `true` | 导出后自动打开文件夹 |

## 测试

```
<引擎目录>\.venv\Scripts\python.exe tests\run_all.py
```

8 套自测：核心工具、译文自检、安装辅助、解包、还原、关钩子、端到端、注入自愈。
不依赖任何特定游戏；需要真实语料的用例在工作区里找不到成对批次时会自动跳过。
安装辅助那一套自带一个临时 HTTP 服务器，专门喂"半截包"来验证下载重试，不需要外网。

## 关于翻译质量

第一版译文由大模型直出，普遍带翻译腔（冠词不落地、"…的东西"名词化、短应答通篇一个词）。
本工具包为此内置了一份方法论：

- [`翻译提示词.md`](翻译提示词.md)：给对话 agent 的作业指导。先写《翻译任务书》
  （人物表/术语表/体例），再按语境翻；第三节第 7 条是翻译腔清单。
  刻意做成**任何游戏通用**——人物与术语由 agent 从语料自己统计，不预填。
- [`docs/翻译腔对照示例.md`](docs/翻译腔对照示例.md)：真实台词的前后对照与病因。
- 若你的环境装了翻译类技能（skill），提示词会引导 agent 优先加载；没装也能自足执行。

## 许可与第三方

本仓库以 **GPL-3.0-or-later** 发布（见 [`LICENSE`](LICENSE)）——因为捆绑了 GPL 的 unrpa。

| 组件 | 许可 | 说明 |
|---|---|---|
| 本仓库 | GPL-3.0-or-later | 外壳、自检、文档 |
| [projz_renpy_translation](https://github.com/abse4411/projz_renpy_translation) | GPL-3.0 | 引擎，**不在本仓库中**，由 `安装.bat` 获取 |
| [unrpa](https://github.com/Lattyware/unrpa) | GPL-3.0 | `.rpa` 解包（`vendor/unrpa/`） |
| [unrpyc](https://github.com/CensoredUsername/unrpyc) | MIT | `.rpyc` 反编译（`vendor/unren/`） |

详见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。

## 免责声明

本工具只处理**你自己拥有或有权修改**的游戏文件。请勿使用它分发受版权保护的作品；
翻译产物（`game/tl/` 下的文本）是否可传播由你与原作的许可条款决定。
`关掉第三方汉化.bat` 用于清除第三方往游戏里塞的注入代码，仅在你自己的游戏副本上操作。
