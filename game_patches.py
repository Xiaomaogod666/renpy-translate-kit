"""生成写进游戏的中文显示补丁。

两个补丁解决"装好了翻译但游戏里看不好"的两类游戏侧问题:

- zzz_cn_font_patch.rpy  字体兜底: 游戏把字体写死在私有样式/常量里时,
  切中文后这些文本仍用纯英文字体渲染成方块。补丁把它们改指中文字体。
- zzz_cn_runtime_bridge.rpy  运行时翻译桥: 数据驱动型游戏(台词存在
  Python 字典里, 运行时调 renpy.say 显示)的动态文本不经过 Ren'Py 的
  翻译管道, tl/ 里的对话翻译对它们无效。补丁包一层 Character 调用,
  显示前用字符串翻译表把文本查一遍再显示。

两个文件都以 zzz_ 开头保证 init 顺序靠后; 游戏卸载(去掉汉化.bat)
会按清单移除它们。
"""
import os

FONT_PATCH_NAME = 'zzz_cn_font_patch.rpy'
BRIDGE_PATCH_NAME = 'zzz_cn_runtime_bridge.rpy'

FONT_PATCH = '''\
# 中文显示字体兜底补丁 (renpy-translate-kit)
# renpy-translate-kit, based on projz_renpy_translation (abse4411/projz_renpy_translation)
#
# 游戏把字体写死在私有样式与常量里(不走 gui.* 变量, i18n 插件的
# 全局字体切换管不到), 切到中文后这些文本会用纯英文字体渲染成方块。
# 本补丁把写死的字体常量与样式属性改指随插件安装的中文字体,
# 并挂到语言切换回调上 —— 切语言后 Ren'Py 会重建样式, 不挂回调
# 补丁只在启动时生效一次。
#
# 卸载: 把游戏目录拖到 去掉汉化.bat 即可(本文件会被一并移除)。

# 注意: 不要在这里 "import renpy"。Ren'Py 会给脚本环境预注入完整的
# renpy 命名空间, 主动 import 会拿一个半初始化的模块对象把它遮蔽掉,
# 导致后续 init 代码(renpy.music 等)全部 AttributeError。

init 900 python:
    # 插件装好的中文字体; 找不到就不动任何东西
    CN_FONT = None
    for _c in ("SourceHanSansLite.ttf", "SourceHanSans-Regular.otf"):
        if renpy.loader.loadable("projz_fonts/" + _c):
            CN_FONT = "projz_fonts/" + _c
            break

    if CN_FONT:
        # 已知的"写死英文字体"的常量名; 不在游戏里的自动跳过
        _FONT_CONSTANTS = (
            "UI_THOUGHT_FONT", "UI_NARRATION_FONT",
            "UI_NAV_FONT", "UI_INTERACTION_FONT", "UI_MAP_LABEL_FONT",
            "UI_INVENTORY_FONT", "UI_STATUS_FONT", "UI_TIME_FONT",
            "UI_DIALOGUE_FONT", "UI_DIALOGUE_NAME_FONT",
            "UI_PHONE_FONT", "UI_PHONE_TITLE_FONT", "UI_PHONE_BUTTON_FONT",
            "UI_PHONE_SMALL_FONT", "UI_PHONE_CONTACT_NAME_FONT",
            "UI_PHONE_APPS_LABEL_FONT", "UI_PHONE_SMS_BUBBLE_FONT",
            "UI_PHONE_CALL_TITLE_FONT", "UI_PHONE_CALL_NAME_FONT",
            "UI_PHONE_CALL_DIALOGUE_FONT", "UI_PHONE_CALL_CONTINUE_FONT",
            "UI_CHOICE_TITLE_FONT", "UI_CONSULTANT_CARD_NAME_FONT",
        )

        # 走 gui.* 变量族的标准字体位
        _GUI_FONT_VARS = (
            "text_font", "interface_text_font", "name_text_font",
            "button_text_font", "choice_button_text_font",
        )

        # 疑似私有对话样式(游戏自定义的 what 样式)
        _STYLE_NAMES = (
            "thought_dialogue", "narration_dialogue",
            "phone_call_title_text", "phone_call_name_text",
            "phone_call_dialogue_text", "phone_call_continue_text",
        )

        def _projz_apply_cn_font():
            # 0. 官方字体替换映射: Ren'Py 渲染每个字体前都会查这张表
            #    (renpy/text/font.py: font_replacement_map.get((fn, bold, italics)))。
            #    screen 里、样式里、常量里写死的字体字面量一并覆盖,
            #    这是唯一能治"输入框 font "fonts/camaro.ttf" 字面量"的手段。
            def _map(fn):
                try:
                    for _b in (False, True):
                        for _i in (False, True):
                            renpy.config.font_replacement_map[(str(fn), _b, _i)] = (CN_FONT, _b, _i)
                except Exception:
                    pass

            # 这个游戏已知写死的字体(不在的话映射了也无害)
            for _fn in ("fonts/camaro.ttf", "fonts/quicksand.ttf",
                        "fonts/familjen.ttf", "fonts/lemonmilk.otf"):
                _map(_fn)

            # 通用兜底: 扫游戏字体目录下真实存在的非中文字体全部映射
            try:
                for _dir in ("game/fonts/", "game/gui/fonts/"):
                    _abs = os.path.join(renpy.config.gamedir, _dir)
                    if os.path.isdir(_abs):
                        for _f in os.listdir(_abs):
                            if _f.lower().endswith((".ttf", ".otf")):
                                _map(_dir + _f)
            except Exception:
                pass

            # 1. 字体常量重定义(只能影响此后新建的样式)
            for _name in _FONT_CONSTANTS:
                if _name in globals():
                    globals()[_name] = CN_FONT

            # 2. gui 层兜底(插件已管, 这里再兜一层)
            for _g in _GUI_FONT_VARS:
                try:
                    setattr(gui, _g, CN_FONT)
                    gui._defaults.setdefault(_g, CN_FONT)
                except Exception:
                    pass

            # 3. 已建好的样式直接改属性
            for _sname in _STYLE_NAMES:
                try:
                    getattr(style, _sname).font = CN_FONT
                except Exception:
                    pass

            # 4. 输入框等 screen 内嵌字体: font_replacement_map 已覆盖字面量,
            #    这里再清一次文本布局缓存让替换立即生效
            try:
                renpy.text.font.font_cache.clear()
            except Exception:
                pass

        _projz_apply_cn_font()

        def _projz_font_on_lang_change(newlang, oldlang):
            _projz_apply_cn_font()

        config.change_language_callbacks.append(_projz_font_on_lang_change)
'''

BRIDGE_PATCH = '''\
# 运行时翻译桥 (renpy-translate-kit)
# renpy-translate-kit, based on projz_renpy_translation (abse4411/projz_renpy_translation)
#
# 数据驱动型游戏把台词存在 Python 字典里, 运行时调 renpy.say / 角色
# 对象显示。这条路径不经过 Ren'Py 的翻译管道(翻译查找只发生在编译好
# 的 say 语句上), 所以 tl/ 里的翻译对它们无效, 游戏里仍旧显示英文。
#
# 挂点说明(踩过的坑, 别改回去):
# - 不能挂 renpy.character.Character: 那是工厂函数, 不是对话类;
# - ADVCharacter.__call__ 在部分游戏里也拦不到(对话可能不走全调用链);
# - ADVCharacter.prefix_suffix 是 i18n 插件验证过的可靠卡口 --
#   每次 say 的 who/what 都会经过它(thing == "what" 时 body 即台词),
#   而且此时语言偏好已经就位。
#
# 查两级表: 字符串翻译表(strings) + 惰性构建的对话映射表
# (原台词 -> 译文, 从 translator.language_translates 全量抽取)。
# 都查不到的行原样显示, 不影响任何原有行为。
#
# 卸载: 把游戏目录拖到 去掉汉化.bat 即可(本文件会被一并移除)。
#
# 同字体补丁: 这里不要 "import renpy", 直接用预注入的 renpy 命名空间。

init 901 python:
    # 对话译文表: {语言: (原文->译文, (who,原文)->译文, 小写原文->译文)}
    # 第三套索引: 游戏常用 .lower() 把按钮文本转小写再显示(键变大写小
    # 混杂原文后与翻译表对不上), 用小写键兜底。
    _bridge_dialogue_maps = {}
    _bridge_dialogue_who_maps = {}
    _bridge_dialogue_lower_maps = {}

    def _bridge_get_dialogue_map(lang):
        if lang not in _bridge_dialogue_maps:
            plain, whoed, lowered = {}, {}, {}
            try:
                lt = renpy.game.script.translator.language_translates
                dt = renpy.game.script.translator.default_translates
                for (ident, l), node in lt.items():
                    if l != lang:
                        continue
                    # 译文: TranslateSay 节点自身带 what; 普通翻译块
                    # 的译文在 block 里的 Say 语句上
                    new = None
                    if getattr(node, "what", None):
                        new = node.what
                    else:
                        for n in getattr(node, "block", []) or []:
                            if getattr(n, "what", None):
                                new = n.what
                                break
                    if not new:
                        continue
                    # 原文: 同 identifier 的默认(英文)节点
                    orig = dt.get(ident)
                    old = getattr(orig, "what", None)
                    if not old or old == new:
                        continue
                    plain[old] = new
                    whoed[(getattr(orig, "who", None), old)] = new
                    lowered[old.lower()] = new
            except Exception:
                pass
            _bridge_dialogue_maps[lang] = plain
            _bridge_dialogue_who_maps[lang] = whoed
            _bridge_dialogue_lower_maps[lang] = lowered
        return (_bridge_dialogue_maps[lang], _bridge_dialogue_who_maps[lang],
                _bridge_dialogue_lower_maps[lang])

    # 小写字符串索引: 游戏常把按钮文本 .lower() 后再显示(Take a nap ->
    # take a nap), 且部分标题在 init 期(语言未应用时)求值后缓存进动作
    # 列表 —— 显示时的文本与字符串表的键大小写对不上。用表的小写键兜底。
    _bridge_strings_lower = {}

    def _bridge_get_strings_lower(lang):
        if lang not in _bridge_strings_lower:
            idx = {}
            try:
                for k, v in renpy.game.script.translator.strings[lang].translations.items():
                    try:
                        idx.setdefault(str(k).lower(), v)
                    except Exception:
                        pass
            except Exception:
                pass
            _bridge_strings_lower[lang] = idx
        return _bridge_strings_lower[lang]

    def _bridge_translate(what, who=None):
        """把一句台词换成译文; 查不到原样返回。任何异常都不外抛。"""
        try:
            lang = renpy.game.preferences.language
        except Exception:
            lang = None
        if not lang or not isinstance(what, str) or not what:
            return what
        try:
            stl = renpy.game.script.translator.strings[lang]
            new = stl.translate(what)
            if new and new != what:
                return new
            # .lower() 过的文本: 大小写对不上精确键, 用小写索引兜底。
            # 注意文本可能【本来就是全小写】(游戏已 .lower() 过) ——
            # 这时 what.lower() == what, 也必须查, 不能跳过。
            hit = _bridge_get_strings_lower(lang).get(what.lower())
            if hit:
                return hit
            plain, whoed, lowered = _bridge_get_dialogue_map(lang)
            hit = whoed.get((who, what))
            if hit is None:
                hit = plain.get(what)
            if hit is None:
                # .lower() 后的文本(小写化按钮标签)按小写键兜底
                hit = lowered.get(what.lower())
            if hit:
                return hit
        except Exception:
            pass
        return what

    try:
        _old_ps = renpy.character.ADVCharacter.prefix_suffix

        def _bridge_prefix_suffix(self, thing, prefix, body, suffix):
            if thing == "what" and isinstance(body, str) and body:
                body = _bridge_translate(body, getattr(self, "name", None))
            return _old_ps(self, thing, prefix, body, suffix)

        renpy.character.ADVCharacter.prefix_suffix = _bridge_prefix_suffix
    except Exception:
        pass

    try:
        # 关键卡口: 台词常被写成 $ line = _("原文") 存变量, say 时传占位符
        # [line_N]。_() 在赋值那一刻查表 —— 读档/切语言晚于赋值时变量里冻结
        # 的还是英文。renpy.substitutions.substitute 先查表再插值, 对占位符
        # 查不到任何东西; 包一层在插值【后】再查一次, 手里就是完整原句。
        _old_sub = renpy.substitutions.substitute

        def _bridge_substitute(s, scope=None, force=False, translate=True):
            res = _old_sub(s, scope, force, translate)
            try:
                # 插值后手里是完整原句(占位符 [line_N] 展开成英文台词) ->
                # 再查一次表, 治"变量冻结了切换前的语言"。
                # 有没有 "[" 都要查: menu 选项 label 不带插值但也不过
                # 翻译管道(menuexports 只 substitute 不查 strings 表),
                # 按钮英文就是漏在这。
                if (translate is not False and isinstance(res[0], str)
                        and res[0] and res[0] != s):
                    new = _bridge_translate(res[0])
                    if new != res[0]:
                        res = (new, res[1])
            except Exception:
                pass
            return res

        renpy.substitutions.substitute = _bridge_substitute
    except Exception:
        pass

    try:
        # menu 选项卡口: 选项 label 在 exports.menu 里只做本地 substitute
        # (变量插值), 完全不查字符串翻译表 —— 按钮/选项英文漏在这。
        # 只挂 exports.menu(AST 的唯一入口); 不能动 renpy.store.menu ——
        # exports.menu 内部会以不同签名调它(ui.menu), 换掉会递归炸签名。
        _old_menu = renpy.exports.menu

        def _bridge_menu(items, *args, **kwargs):
            try:
                if items:
                    fixed = []
                    for it in items:
                        if isinstance(it, tuple) and it and isinstance(it[0], str):
                            label = _bridge_translate(it[0])
                            if label != it[0]:
                                it = (label,) + tuple(it[1:])
                        fixed.append(it)
                    items = fixed
            except Exception:
                pass
            return _old_menu(items, *args, **kwargs)

        renpy.exports.menu = _bridge_menu
    except Exception:
        pass

    try:
        # 终极卡口: 所有屏幕文本显示前必经 Text.set_text。
        # 主题按钮(load 等)、交互动作(take a nap)、状态栏(week/time)这些
        # 文本由 _() 在脚本求值时翻译 —— 求值早于切语言时结果被缓存进
        # lambda/状态对象, 且显示路径不经过 substitute, 前面的卡口全
        # 摸不到。在这层对最终显示文本查表, 全部兜住。
        # (切语言后 per_interact 会用原始参数重跑 set_text, 本层自动
        #  全屏重查一遍。i18n 插件的字体标签在 self.text 上后处理,
        #  与本层只改传入文本互不干扰。)
        _old_set_text = renpy.text.text.Text.set_text

        def _bridge_set_text(self, text, scope=None, substitute=False, update=True):
            try:
                lang = renpy.game.preferences.language
            except Exception:
                lang = None
            if lang and isinstance(text, list):
                try:
                    nt = []
                    changed = False
                    for i in text:
                        if isinstance(i, str) and i:
                            j = _bridge_translate(i)
                            if j != i:
                                i = j
                                changed = True
                        nt.append(i)
                    if changed:
                        text = nt
                except Exception:
                    pass
            elif lang and isinstance(text, str) and text:
                text = _bridge_translate(text)
            return _old_set_text(self, text, scope, substitute, update)

        renpy.text.text.Text.set_text = _bridge_set_text
    except Exception:
        pass

    try:
        # 双保险: 运行时直接调角色对象显示的路径
        _cls = renpy.character.ADVCharacter
        _old_call = _cls.__call__

        def _bridge_call(self, what, *args, **kwargs):
            what = _bridge_translate(what, getattr(self, "name", None))
            return _old_call(self, what, *args, **kwargs)

        _cls.__call__ = _bridge_call
    except Exception:
        pass
'''


def _patch_path(game_path, name):
    return os.path.join(game_path, 'game', name)


def font_patch_path(game_path):
    return _patch_path(game_path, FONT_PATCH_NAME)


def bridge_patch_path(game_path):
    return _patch_path(game_path, BRIDGE_PATCH_NAME)


def write_display_patches(game_path):
    """把两个补丁写进 game/。返回写了的文件路径列表。

    幂等: 内容不变时不重写(避免改动 mtime 触发无谓的重编译)。
    """
    written = []
    for name, content in ((FONT_PATCH_NAME, FONT_PATCH),
                          (BRIDGE_PATCH_NAME, BRIDGE_PATCH)):
        path = _patch_path(game_path, name)
        try:
            if os.path.isfile(path):
                with open(path, encoding='utf-8') as f:
                    if f.read() == content:
                        continue
        except OSError:
            pass
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
        written.append(path)
    return written
