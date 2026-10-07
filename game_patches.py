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
# 本补丁包一层 Character 调用, 显示前查两级表:
#   1. 字符串翻译表(strings, UI/字符串通道的译文);
#   2. 对话译文表: 首次用到时从 translator.language_translates 里
#      把 "原台词 -> 译文" 全量抽出来(数据驱动游戏的动态台词在导出时
#      都以对话通道进过 tl/, 所以能对上)。
# 两级都查不到的行原样显示, 不影响任何原有行为。
#
# 卸载: 把游戏目录拖到 去掉汉化.bat 即可(本文件会被一并移除)。
#
# 同字体补丁: 这里不要 "import renpy", 直接用预注入的 renpy 命名空间。

init 901 python:
    def _projz_bridge_make_wrapper(cls):
        old_call = cls.__call__

        # 对话译文表: {语言: {(who or None, 原文): 译文}} —— 惰性构建
        _dialogue_maps = {}
        _dialogue_who_maps = {}

        def _get_dialogue_map(lang):
            if lang not in _dialogue_maps:
                plain, whoed = {}, {}
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
                except Exception:
                    pass
                _dialogue_maps[lang] = plain
                _dialogue_who_maps[lang] = whoed
            return _dialogue_maps[lang], _dialogue_who_maps[lang]

        def call(self, what, *args, **kwargs):
            try:
                lang = renpy.game.preferences.language
            except Exception:
                lang = None
            if lang and isinstance(what, str) and what:
                try:
                    stl = renpy.game.script.translator.strings[lang]
                    new = stl.translate(what)
                    if new and new != what:
                        what = new
                    else:
                        plain, whoed = _get_dialogue_map(lang)
                        hit = whoed.get((getattr(self, "name", None), what))
                        if hit is None:
                            hit = plain.get(what)
                        if hit and hit != what:
                            what = hit
                except Exception:
                    pass
            return old_call(self, what, *args, **kwargs)

        return call

    try:
        _Character = renpy.character.Character
        _Character.__call__ = _projz_bridge_make_wrapper(_Character)
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
