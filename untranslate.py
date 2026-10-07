"""去掉游戏里的汉化：删掉本工具包生成的译文与注入文件，把游戏还原成原版。

用法（由 去掉机翻.bat 调用）:
    untranslate.py <游戏目录>         预览后确认，再执行
    untranslate.py <游戏目录> -y      不确认，直接执行
    untranslate.py <游戏目录> -n      只看预览，什么都不改

判定「是我们的产物」只看译文文件里的工具 banner：
    abse4411/projz_renpy_translation
游戏自带/其它工具生成的语言包没有这行，所以不会被误删。
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import time
import traceback

KIT_DIR = os.path.dirname(os.path.abspath(__file__))

# 本工具包生成的 .rpy 都带这个 banner；原生语言包没有。
BANNER = b'abse4411/projz_renpy_translation'
# 注入到 screens.rpy 的那一行。只认这个按钮，不碰 screens.rpy 的其它内容。
BUTTON_KEY = 'projz_i18n_settings'
BUTTON_RE = re.compile(
    r'^\s*textbutton _\("I18n settings"\) action Show\("projz_i18n_settings"\)\s*$')

# 注入文件本体（写基名，脚本自己补 .rpy/.rpyc）
PROJZ_FILES = ('projz_injection', 'projz_i18n_inject',
               'zzz_cn_font_patch', 'zzz_cn_runtime_bridge')
FONT_DIR = 'projz_fonts'
# 运行时缓存，游戏自己会重建；只删这几个，不动 cache 里别的东西
CACHE_FILES = ('bytecode.rpyb', 'pyanalysis.rpyb', 'screens.rpyb')


def load_kit():
    """借用 kit.py 的输出函数、配置与目录校验，保证风格与提示一致。"""
    spec = importlib.util.spec_from_file_location('kit', os.path.join(KIT_DIR, 'kit.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


kit = load_kit()


def _print_usage():
    print()
    print('=' * 64)
    print('  RenPy 游戏翻译 —— 去掉汉化（还原原版）')
    print('=' * 64)
    print()
    print('  把【游戏目录】拖到 去掉机翻.bat 上')
    print('      -> 删掉本工具包生成的译文和注入文件')
    print('      (拖游戏的 .exe 文件也行,效果一样)')
    print()
    print('  执行前会先列出要删什么、备份到哪，确认后才动手。')
    print('  备份留在 workspace 里，想恢复汉化把它复制回游戏目录即可。')
    print()
    print('  详细说明见同目录的 使用说明.md')
    print()


# ---------------------------------------------------------------- 只读扫描

def _head_has_banner(path, limit=65536):
    try:
        with open(path, 'rb') as f:
            return BANNER in f.read(limit)
    except OSError:
        return False


def _rel(game_path, path):
    try:
        return os.path.relpath(path, game_path)
    except ValueError:
        return path


def scan(game_path):
    """找出所有属于本工具包的痕迹，一个字节都不改。"""
    game_dir = os.path.join(game_path, 'game')
    tl_dir = os.path.join(game_dir, 'tl')

    found = {
        'tl_langs': {},       # 语言 -> {'files': [...], 'rpyc': [...]}
        'orphan_rpyc': [],    # 同语言目录里没有对应 .rpy 的 .rpyc（只报告）
        'other_langs': [],    # 没动过的语言包
        'projz_files': [],
        'font_dir': None,
        'screens': None,
        'screens_lines': [],
        'cache': [],
        'stray': [],          # game/tl 之外带 banner 的 .rpy（只报告）
    }

    # 1) 译文：game/tl/*/ 下带 banner 的 .rpy，连带它的 .rpyc
    if os.path.isdir(tl_dir):
        for lang in sorted(os.listdir(tl_dir)):
            lang_dir = os.path.join(tl_dir, lang)
            if not os.path.isdir(lang_dir):
                continue
            marked, paired_rpyc = [], []
            all_rpyc = []
            for root, dirs, files in os.walk(lang_dir):
                for fn in files:
                    p = os.path.join(root, fn)
                    low = fn.lower()
                    if low.endswith('.rpy') and _head_has_banner(p):
                        marked.append(p)
                    elif low.endswith('.rpyc'):
                        all_rpyc.append(p)
            if not marked:
                continue
            for p in marked:
                c = p[:-4] + '.rpyc'
                if os.path.isfile(c):
                    paired_rpyc.append(c)
            orphan = [c for c in all_rpyc
                      if not os.path.isfile(c[:-5] + '.rpy') and c not in paired_rpyc]
            found['tl_langs'][lang] = {'files': marked, 'rpyc': paired_rpyc}
            found['orphan_rpyc'].extend(orphan)
        for lang in sorted(os.listdir(tl_dir)):
            if os.path.isdir(os.path.join(tl_dir, lang)) and lang not in found['tl_langs']:
                found['other_langs'].append(lang)

    # 2) 注入文件与字体
    for name in PROJZ_FILES:
        for ext in ('.rpy', '.rpyc'):
            p = os.path.join(game_dir, name + ext)
            if os.path.isfile(p):
                found['projz_files'].append(p)
    fd = os.path.join(game_dir, FONT_DIR)
    if os.path.isdir(fd):
        found['font_dir'] = fd

    # 3) screens.rpy 里我们插的那一行
    screens = os.path.join(game_dir, 'screens.rpy')
    if os.path.isfile(screens):
        try:
            with open(screens, encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
        except OSError:
            lines = []
        hit = [i for i, ln in enumerate(lines)
               if BUTTON_RE.match(ln) or (BUTTON_KEY in ln and 'textbutton' in ln)]
        if hit:
            found['screens'] = screens
            found['screens_lines'] = hit

    # 4) 运行时缓存
    for name in CACHE_FILES:
        p = os.path.join(game_dir, 'cache', name)
        if os.path.isfile(p):
            found['cache'].append(p)

    # 5) 兜底检查：game/tl 之外还有没有带 banner 的 .rpy（已列入删除的除外）
    known = {os.path.normcase(p) for p in found['projz_files']}
    skip = (os.path.normcase(tl_dir), os.path.normcase(os.path.join(game_dir, 'cache')))
    for root, dirs, files in os.walk(game_dir):
        if os.path.normcase(root) in skip:
            dirs[:] = []
            continue
        for fn in files:
            if fn.lower().endswith('.rpy'):
                p = os.path.join(root, fn)
                if os.path.normcase(p) in known:
                    continue
                if _head_has_banner(p):
                    found['stray'].append(p)

    return found


def has_anything(found):
    return bool(found['tl_langs'] or found['projz_files'] or found['font_dir']
                or found['screens'] or found['cache'])


# ---------------------------------------------------------------- 工具侧状态

def index_record(db_path, game_path):
    """在工具索引里找到这个游戏的记录（TinyDB 就是普通 JSON）。"""
    if not os.path.isfile(db_path):
        return None, None
    try:
        with open(db_path, encoding='utf-8') as f:
            return json.load(f), db_path
    except Exception:
        return None, db_path


def find_injection_record(data, game_path):
    want = kit.norm(game_path)
    for key, rec in (data or {}).get('_default', {}).items():
        proj = (rec or {}).get('project') or {}
        path = proj.get('project_path')
        if path and kit.norm(path) == want:
            state = proj.get('injection_state') or {}
            return key, state
    return None, None


# ---------------------------------------------------------------- 备份与删除

def backup(backup_root, game_path, found, index_db):
    """把要删/要改的东西按原目录结构备份出来。返回备份路径。"""
    n = 0
    for lang, item in found['tl_langs'].items():
        src = os.path.join(game_path, 'game', 'tl', lang)
        dst = os.path.join(backup_root, 'game', 'tl', lang)
        shutil.copytree(src, dst)
        n += len(item['files']) + len(item['rpyc'])
    for p in found['projz_files']:
        dst = os.path.join(backup_root, _rel(game_path, p))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(p, dst)
        n += 1
    if found['font_dir']:
        shutil.copytree(found['font_dir'],
                        os.path.join(backup_root, _rel(game_path, found['font_dir'])))
        n += sum(len(f) for _, _, f in os.walk(found['font_dir']))
    if found['screens']:
        for ext in ('.rpy', '.rpyc'):
            p = found['screens'][:-4] + ext
            if os.path.isfile(p):
                dst = os.path.join(backup_root, _rel(game_path, p))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(p, dst)
                n += 1
    for p in found['cache']:
        dst = os.path.join(backup_root, _rel(game_path, p))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(p, dst)
        n += 1
    if index_db and os.path.isfile(index_db):
        dst = os.path.join(backup_root, '_tool', 'index.db')
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(index_db, dst)
        n += 1
    return n


def remove(paths):
    done = 0
    for p in paths:
        try:
            os.remove(p)
            done += 1
        except FileNotFoundError:
            continue
    return done


def prune_empty_dirs(top):
    """删掉被搬空的目录（只删空的）。"""
    removed = 0
    for root, dirs, files in os.walk(top, topdown=False):
        if root == top:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
                removed += 1
        except OSError:
            pass
    try:
        if os.path.isdir(top) and not os.listdir(top):
            os.rmdir(top)
            removed += 1
    except OSError:
        pass
    return removed


def strip_screens_line(path, indices):
    """按行删掉注入行；写完返回删掉的行数。"""
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    keep = [ln for i, ln in enumerate(lines) if i not in set(indices)]
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        f.writelines(keep)
    os.replace(tmp, path)
    return len(lines) - len(keep)


def reset_index_state(db_path, data, key):
    """把索引里这个游戏的注入状态改回「未注入」。"""
    rec = data['_default'][key]
    proj = rec.setdefault('project', {})
    state = proj.setdefault('injection_state', {})
    before = dict(state)
    state['Base'] = False
    state['I18n'] = False
    tmp = db_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, db_path)
    return before


# ---------------------------------------------------------------- 预览

def show_plan(game_path, found, backup_root):
    kit.banner(f'去掉汉化: {os.path.basename(game_path)}')
    print(f'  游戏目录: {game_path}')
    print()

    print('  将删除 (都已备份):')
    for lang, item in sorted(found['tl_langs'].items()):
        cnt = len(item['files']) + len(item['rpyc'])
        print(f'    译文    game\\tl\\{lang}\\  —— {cnt} 个文件 (本工具生成的机翻)')
    for base in PROJZ_FILES:
        hits = [p for p in found['projz_files']
                if os.path.basename(p).startswith(base + '.')]
        if not hits:
            continue
        names = os.path.basename(hits[0])
        extra = ''.join(' (+ .' + os.path.basename(p).rsplit('.', 1)[1] + ')'
                        for p in hits[1:])
        print(f'    注入    game\\{names}{extra}')
    if found['font_dir']:
        cnt = sum(len(f) for _, _, f in os.walk(found['font_dir']))
        print(f'    注入    {_rel(game_path, found["font_dir"])}\\  —— {cnt} 个字体')
    if found['cache']:
        names = ', '.join(os.path.basename(p) for p in found['cache'])
        print(f'    缓存    game\\cache\\{names}   (游戏下次启动自己重建)')
    if found['screens']:
        idx = ', '.join(str(i + 1) for i in found['screens_lines'])
        print(f'    改行    game\\screens.rpy 第 {idx} 行 —— 去掉 "I18n settings" 按钮')
    if found['index_db_key']:
        print('    状态    工具索引里把这个游戏标记为「未注入」(译文库保留)')

    print()
    print('  不会动:')
    print('    game\\saves\\ 存档、游戏自己的脚本与图片音频')
    if found['other_langs']:
        print('    游戏自带的其它语言包: ' + ', '.join(found['other_langs']))
    else:
        print('    游戏自带的其它语言包 (当前没有)')
    print()
    if found['orphan_rpyc']:
        print('  需要你自己判断 (没有同名 .rpy，可能是原生语言包，没动):')
        for p in found['orphan_rpyc']:
            print(f'    {_rel(game_path, p)}')
        print()
    if found['stray']:
        print('  注意: game\\tl\\ 之外还有带工具标记的 .rpy，没动，请自行确认:')
        for p in found['stray']:
            print(f'    {_rel(game_path, p)}')
        print()
    print(f'  备份到: {backup_root}')
    print()


# ---------------------------------------------------------------- 主流程

def main():
    dry = yes = False
    rest = []
    for a in sys.argv[1:]:
        if a in ('-n', '--dry-run'):
            dry = True
        elif a in ('-y', '--yes'):
            yes = True
        elif a in ('-h', '--help'):
            _print_usage()
            return 0
        else:
            rest.append(a)

    target = ' '.join(rest).strip().strip('"').strip()
    if not target:
        _print_usage()
        return 1

    if not os.path.exists(target):
        kit.die(f'这个路径不存在: {target}',
                '路径里有空格时请连同引号一起拖，或把文件复制到简单一点的路径再试。')
    if os.path.isfile(target):
        if not target.lower().endswith('.exe'):
            kit.die(f'不认识这个文件类型: {os.path.basename(target)}',
                    '请拖游戏目录，或游戏目录里的 .exe。')
        target = os.path.dirname(os.path.abspath(target))

    game_path = kit.validate_game_dir(target)
    cfg = kit.load_config()
    found = scan(game_path)

    backup_root = os.path.join(cfg['workspace'], kit.safe_name(os.path.basename(game_path)),
                               '_还原备份', time.strftime('%Y%m%d-%H%M%S'))

    if not has_anything(found):
        kit.banner(f'{os.path.basename(game_path)} 里没有发现汉化痕迹')
        print('  译文、注入文件都不在，可能已经还原过，或者这个游戏没用过本工具。')
        print()
        if found['other_langs']:
            print('  游戏自带语言包: ' + ', '.join(found['other_langs']))
            print()
        return 0

    # 工具索引状态（改之前先读出来，预览要显示）
    index_db = os.path.join(cfg['tool_dir'], 'projz', 'index.db')
    data, index_db = index_record(index_db, game_path)
    key, state = find_injection_record(data, game_path)
    found['index_db_key'] = key if (state and (state.get('Base') or state.get('I18n'))) else None

    show_plan(game_path, found, backup_root)

    if dry:
        kit.info('这是预览模式 (-n)，什么都没有改动。')
        print()
        return 0

    if not yes:
        try:
            ans = input('  确认执行? 输入 y 回车 (其它任意键取消): ').strip().lower()
        except EOFError:
            print()
            kit.fail('没有收到确认，已取消，什么都没有改动。')
            print()
            return 1
        if ans != 'y':
            print()
            kit.info('已取消，什么都没有改动。')
            print()
            return 0

    # 游戏在跑就会删不掉，先探一下
    probe = os.path.join(game_path, 'game', 'screens.rpy')
    if not os.path.isfile(probe):
        probe = os.path.join(game_path, 'game')
    try:
        if os.path.isfile(probe):
            with open(probe, 'r+b'):
                pass
        else:
            os.listdir(probe)
    except OSError:
        kit.die('游戏文件被占用，多半是游戏还开着。',
                '请先完全退出游戏（含启动器窗口），再运行这个脚本。')

    kit.banner('正在备份并还原')
    try:
        n = backup(backup_root, game_path, found, index_db)
        kit.ok(f'已备份 {n} 个文件到 {backup_root}')

        removed = 0
        for lang, item in sorted(found['tl_langs'].items()):
            removed += remove(item['files']) + remove(item['rpyc'])
            prune_empty_dirs(os.path.join(game_path, 'game', 'tl', lang))
            if os.path.isdir(os.path.join(game_path, 'game', 'tl', lang)):
                kit.ok(f'译文已移除: game\\tl\\{lang}\\ (目录里还有别的文件，保留)')
            else:
                kit.ok(f'译文已移除: game\\tl\\{lang}\\')
        removed += remove(found['projz_files'])
        if found['projz_files']:
            kit.ok('注入文件已移除: ' + ', '.join(os.path.basename(p) for p in found['projz_files']))
        if found['font_dir']:
            shutil.rmtree(found['font_dir'], ignore_errors=True)
            kit.ok('注入字体已移除: game\\projz_fonts\\')
        removed += remove(found['cache'])
        if found['cache']:
            kit.ok('运行时缓存已清除（游戏下次启动自己重建）')

        if found['screens']:
            nl = strip_screens_line(found['screens'], found['screens_lines'])
            rpyc = found['screens'][:-4] + '.rpyc'
            if os.path.isfile(rpyc):
                remove([rpyc])
            kit.ok(f'game\\screens.rpy 已还原（删掉 {nl} 行），旧 .rpyc 已清除')

        prune_empty_dirs(os.path.join(game_path, 'game', 'tl'))

        if found['index_db_key']:
            try:
                before = reset_index_state(index_db, data, found['index_db_key'])
                kit.ok(f'工具索引状态已重置 (之前 Base={before.get("Base")}, I18n={before.get("I18n")})')
            except Exception as e:
                kit.fail(f'工具索引状态没改成: {e}（不影响游戏，译文库还在）')

        # 复核
        print()
        left = scan(game_path)
        if has_anything(left):
            kit.fail('还有残留，请把上面的列表发给开发者:')
            for lang, item in left['tl_langs'].items():
                print(f'         game\\tl\\{lang}\\')
            for p in left['projz_files']:
                print(f'         {_rel(game_path, p)}')
            if left['font_dir']:
                print(f'         {_rel(game_path, left["font_dir"])}')
            if left['screens']:
                print('         game\\screens.rpy')
            print()
            return 1

        kit.banner('完成')
        print('  游戏的汉化已去掉，下次启动就是原版英文。')
        print()
        print('  想重新装回汉化或继续翻译:')
        print(f'    译文库和索引都留着，按 使用说明.md 正常走一遍即可。')
        print(f'    完整备份（含还原前的 screens.rpy）: {backup_root}')
        print()
        return 0
    except OSError as e:
        print()
        kit.fail(f'写入时出错: {e}')
        print(f'         已备份的内容仍在: {backup_root}')
        print('         如果提示「拒绝访问」，请先完全退出游戏再重试。')
        print()
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except KeyboardInterrupt:
        print()
        print('  已取消。')
        sys.exit(130)
    except Exception as e:
        print()
        kit.fail(f'出了个意外错误: {e}')
        print(traceback.format_exc())
        sys.exit(1)
