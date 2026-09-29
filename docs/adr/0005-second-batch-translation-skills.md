# 0005. 第二批翻译技能: 工程化流水线 + 中文去模板化 + 引擎知识补漏

日期: 2026-09-29
状态: 已采用

## 背景

0004 装了第一批两个技能 (`en-zh-translation-polish` 管「怎么写得不别扭」、
`renpy-translation` 管「有什么工程约束」) 之后, 用户开了代理并要求继续找。第一批受限于只能靠市场扫描, 未覆盖三个明显缺口:

1. **没有流水线/审校机制** —— 提示词只有「翻译」这一步, 没有「谁来独立检查」的角色分离。
   一批 9796 行全靠单个 agent 自译自检时, 自检等于复读自己的判断。
2. **没有中文侧的去模板化清单** —— 第一批两份方法论都是「英译汉」视角,
   病症表按英语结构组织 (形合迁移、定语堆叠); 而「的字层叠」「进行＋动词」「套话收尾」
   这类是**中文自身的模板化痕迹**, 换个视角才看得见。
3. **Ren'Py 引擎知识有两处硬缺口** —— `translate_string()` 决定译文该进哪个翻译节、
   以及模型会把 `{b}` 写成 `{/b}` 导致游戏崩行。两者都不在已装技能里。

## 采用

装了三个新技能, 另有两处知识以文件级摘录补进已装技能。全部 MIT, 逐文件 md5 校验后手工放目录。

### 新装

- **`translate-visual-novel`** (`9029kazuki/codex-visual-novel-translation` @ `d9933ab7750d`, MIT)
  —— 本批唯一的**工程化流水线**。11 步管线 + 12 阶段状态机, 任务 7 态
  (pending→assigned→translated→validated→reviewed→approved→merged)、单写者、
  `--invalidate` 定向重审。最有价值的是 `references/translation-contract.md` 的**译文合同**:
  - 五级优先级: 剧情事实/逻辑/否定/模态/时间 > 说话人/指代/视角/知识状态 >
    人设/情感/关系距离/称谓 > 目标语节奏 > 原文表层语序。
  - **不确定要写进结构化 `issues` 字段, 不许藏进流畅的译文里** ——
    「别猜」从一句口号变成了输出格式的一部分。
  - 保留有意暧昧/误导/停顿/口吃/中断/未说完; 不把后续路线知识写进更早的台词。
  - 审校独立性的机制化: 审校者用 sparse delta + digest/coverage 声明,
    且系统拒绝「伪造另一位审校者身份通过独立门禁」。
- **`translate-polisher`** (`rookie-ricardo/erduo-skills` @ `1fb6ec5df76c`, MIT, 935★)
  —— 精翻四步法(分析→初译→审校→终稿), 风格预设 10 种(含 `humorous`, 本批唯一提幽默的),
  长文分块(≤5000 词/块, 各 subagent 并行)+ 接缝检查。最可迁移的一条是句式规矩:
  **「短句处理——区分节奏型与修辞型」**, 修辞性独立短句 (如 `That'll do it.`)
  必须保留独立成句, 并入前句会杀死修辞效果。
- **`humanizer-zh`** (`op7418/Humanizer-zh` @ `f4518a8eab97`, MIT, **18643★**)
  —— 中文去 AI 痕/模板化, **31 条模式分 A–F 组**。A 组铺垫代替陈述、B 组公式化节奏、
  C 组拔高与借权威、D 组公式化排版、E 组聊天草稿残留, 而 **F 组是中文表达补充**
  (「的」字层叠、「进行＋动词」、被字句堆叠、四字词排比、「随着…的发展」式开头、套话收尾)
  —— 这一组正对本 kit 的机翻味问题。核心约束写得很稳: 保留信息和确定程度、
  不增事实数字、保留否定/比较/归因/模态、**模式清单是线索不是黑名单**。
  附 `tests/check_structure.py` 与 fixtures。

### 摘录(不整装)

- **`3060226349kk-cmd/en-zh-max`** (@ `1675cbe1e814`, MIT) —— 经 md5 比对确认它的
  `translationese-symptoms.md` / `techniques.md` / `text-analysis-and-qa.md` 与已装的
  `en-zh-translation-polish` **逐字节相同** (同源), 所以**不重复装**;
  只摘它独有的两份语域参考进已装技能的 `reference/`:
  - `literary-fiction-sexual-register.md` —— 文学文本里临床词与口语词**混用**时
    「跟随原文切换, 不作语域归一化」; 判据是**词频比例**
    (`penis` 44 : `cock` 11 → 临床是默认档, 口语是有限度降格)。
  - `libertine-vocabulary.md` —— 直译向词汇对照表 (cock→鸡巴, cunt→屄, fuck→干/操),
    原则「不自我审查、不升级为医学术语、不降级为儿童用语」。
  对 VN 尤其是成人向文本, 这是最常翻车的一类。
  (该仓库含一个自称 `en-zh-ultra/*/SKILL.md` 的阶段 `-0.5`, 但那些子技能在仓库里不存在,
  属断链, 这也是不整装的另一个理由。)

### 引擎知识补漏(进已装 `renpy-translation`)

来源 `loggg4823-create/renpy-translate` (@ `f9a97d8500c2`)。该仓库整体不装
(一半与已装技能重复、依赖 `DEEPSEEK_API_KEY`、无测试), 但两处是真缺口:

- **`strings:` vs `dialogue:` 的判定** —— 若 screens.rpy 里有 `renpy.translate_string()`,
  则**所有**译文必须放 `translate <lang> strings:` 节, 放进 dialogue 块会静默不生效。
  源码级根因: `renpy/parser.py` 仅当 identifier == `strings` 才建 `TranslateString` 节点;
  `renpy/ast.py` 的 `Translate.execute` 抛 "Translation nodes cannot be run directly.";
  而 `renpy.translate_string()` 只查字符串翻译表。写进了
  `references/native-translate-blocks.md`(该文原本没有这一判定)。
- **反转文本标签** —— 模型把 `{b}` 当 HTML 写成 `{/b}`, 实例
  `"Oh {b}FUCK{/b}!" → "哦{/b}操{/b}！"`, Ren'Py 抛
  `'/b' closes a text tag that isn't open.` 全行崩溃。写进 `references/qa.md`:
  成因 + 双防线(提示词 CRITICAL 规则 + 深度栈式 `fix_inverted_tags()`)。
  已装技能有 `TAGNEST` 检测但无修复手段。
- 另附三条实务坑: 跨文件与文件内双重去重(否则 `A translation for '...' already exists`)、
  改完必须删 `.rpyc` 缓存、Windows 中文路径 `realpath` 乱码。

## 配套改动

- `翻译提示词.md` 开工前一段列全五个技能及其分工; 第三节第 7 条补 3 项
  (四字词别排比堆砌、别套话收尾、修辞性短句要独立成句)。
- `CONTEXT.md` 翻译技能词条扩到五个, 并注明第三批增补的两处引擎知识。
- `使用说明.md` 「机翻味太重怎么办」一节与「文件都放在哪」表同步。
- `en-zh-translation-polish/reference/VENDORED.md` 记参考文件出处与 HEAD,
  便于日后比对上游更新。

## 后果

- **五个技能有重叠但不冗余**: 方法论(第一批)管「怎么写」, 合同与流水线(第二批)管
  「谁来查、查出问题怎么记账」, 去模板化清单管「中文自己的毛病」,
  引擎知识管「哪些错误会直接崩游戏」。删除任一技能仍可运行 —— 提示词自足。
- **装备了但尚未在真实批次上跑过**: 本批技能的收益需要下一批真实翻译才能量化
  (第一批已验证过 20 条句子的润色效果)。
- 手工安装的技能不随客户端更新; 升级客户端后需重新放回 `~/.zcode/skills/`。
- 判定为「不装」的候选及理由记在 ADR 之外的调研结论里;
  `tokyboop/game-localization-skill` 是雾件(核心逻辑全注释掉), `jjzeff/jjzeff-skills`
  无 LICENSE 且方向相反, 都不符合 vendor 条件。
