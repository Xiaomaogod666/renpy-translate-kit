"""拖拽工具包的核心驱动。

用法（由 翻译.bat 调用）:
    kit.py <游戏目录>      -> 导出全部未翻译文本
    kit.py <JSON 文件>     -> 把译文装回游戏
"""
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import traceback

KIT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, KIT_DIR)
VENDOR_DIR = os.path.join(KIT_DIR, 'vendor')
UNREN = os.path.join(VENDOR_DIR, 'unren', 'unrpyc.py')

import game_patches  # noqa: E402  游戏侧中文显示补丁(字体兜底 + 运行时翻译桥)

SCRIPT_EXTS_RE = re.compile(r'\.(rpy|rpyc|rpym|rpymc)$', re.IGNORECASE)

# 翻译 part 的命名法: <基础名>_<编号>_translated.json (基础名 = 游戏名_语言)
PART_RE = re.compile(r'^(?P<root>.+)_(?P<num>\d+)_translated$', re.IGNORECASE)
# 通用分块命名: part<编号>.json / part<编号>_<后缀>.json (翻译会话拆块常用)
PART_FILE_RE = re.compile(r'^part(?P<num>\d+)(_\w+)?$', re.IGNORECASE)

OK = '  [OK]   '
NO = '  [失败] '
GO = '  ...   '


# ---------------------------------------------------------------- 输出工具

def info(msg):
    print(f'{GO}{msg}')


def ok(msg):
    print(f'{OK}{msg}')


def fail(msg):
    print(f'{NO}{msg}')


def banner(msg):
    print()
    print('=' * 64)
    print(f'  {msg}')
    print('=' * 64)


def die(msg, hint=None):
    print()
    fail(msg)
    if hint:
        print()
        for line in hint.strip().splitlines():
            print(f'         {line.strip()}')
    print()
    sys.exit(1)


# ---------------------------------------------------------------- 配置

DEFAULT_CONFIG = {
    'tool_dir': '../projz_renpy_translation',
    'workspace': '../workspace',
    'target_language': 'schinese',
    'export_limit': 0,
    'open_folder_after_export': True,
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    path = os.path.join(KIT_DIR, 'kit.json')
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception as e:
            die(f'配置文件 kit.json 读取失败: {e}',
                '请检查它的格式是否正确(JSON),或直接删掉它使用默认配置。')
    cfg['tool_dir'] = os.path.normpath(os.path.join(KIT_DIR, cfg['tool_dir']))
    cfg['workspace'] = os.path.normpath(os.path.join(KIT_DIR, cfg['workspace']))
    return cfg


# ---------------------------------------------------------------- 工具接入

def enter_tool_dir(cfg):
    """工具内部用的是相对路径('./projz'),必须站在它自己的目录里运行。"""
    tool_dir = cfg['tool_dir']
    if not os.path.isdir(tool_dir):
        die(f'找不到翻译工具本体: {tool_dir}',
            '请确认 projz_renpy_translation 和 renpy_translate_kit 在同一个目录下。')
    os.chdir(tool_dir)
    sys.path.insert(0, tool_dir)


def import_tool():
    try:
        import log  # noqa: F401  启用工具的日志
        from command.manage import execute_cmd, exists_cmd  # noqa: F401
        from store import TranslationIndex
        from injection.renpy import check_renpy_dir, check_project_name
        return {
            'execute_cmd': execute_cmd,
            'exists_cmd': exists_cmd,
            'TranslationIndex': TranslationIndex,
            'check_renpy_dir': check_renpy_dir,
            'check_project_name': check_project_name,
        }
    except Exception as e:
        die(f'翻译工具加载失败: {e}',
            '这通常表示依赖没装全，或 projz_renpy_translation 目录不完整。\n'
            '完整报错:\n' + traceback.format_exc())


def run_command(tool, cmd, args, what):
    """执行工具内部命令;返回 True/False。"""
    try:
        tool['execute_cmd'](cmd, args)
        return True
    except AssertionError as e:
        fail(f'{what}失败: {e}')
        return False
    except Exception as e:
        fail(f'{what}出错: {e}')
        print(traceback.format_exc())
        return False


# ---------------------------------------------------------------- 游戏目录检查

def validate_game_dir(path):
    """确认拖进来的是 RenPy 游戏根目录(含 exe 的那一层)。"""
    if not os.path.isdir(path):
        die(f'这不是一个目录: {path}')
    path = os.path.abspath(path)

    base = os.path.basename(path)
    if base.lower() in ('game', 'lib', 'renpy'):
        die(f'你拖的是 "{base}" 子目录,不是游戏根目录。',
            f'请拖它上面一层,也就是含 exe 的那一层:\n{os.path.dirname(path)}')

    for d in ('game', 'lib', 'renpy'):
        if not os.path.isdir(os.path.join(path, d)):
            die(f'这个目录不像 RenPy 游戏: 缺少 "{d}" 目录。',
                f'当前目录: {path}\n'
                '请拖含游戏 exe 的那一层(里面应该能看到 game、lib、renpy 三个目录)。')

    exes = [f for f in os.listdir(path) if f.lower().endswith('.exe')]
    if not exes:
        die('这个游戏目录里没有 exe 文件,无法识别入口。',
            f'当前目录: {path}')
    return path


# ---------------------------------------------------------------- 解包检查与自动解包

def rpa_entry_game_rel(entry):
    """把 RPA 包内条目路径归一成「相对游戏根目录」的路径。

    标准 Ren'Py 打包的条目自带 game/ 前缀;但也有游戏打包时不带
    (条目形如 content/xxx.rpyc、script.rpyc)。引擎运行时把这些条目
    当作 game/ 下的文件来加载,这里对齐同样的语义统一归入 game/ ——
    否则脚本会被解到游戏根目录,游戏和导出流程都看不见那里。
    """
    entry = entry.replace('\\', '/').lstrip('/')
    if not entry:
        return entry
    if entry.split('/', 1)[0].lower() == 'game':
        return entry
    return 'game/' + entry


def find_rpa_files(game_dir):
    found = []
    for root, dirs, files in os.walk(game_dir):
        dirs[:] = [d for d in dirs if d.lower() not in ('lib', 'renpy', 'projz')]
        for f in files:
            if f.lower().endswith('.rpa'):
                found.append(os.path.join(root, f))
    return found


def find_undecoded_rpyc(game_dir):
    """找出还没还原成明文脚本的 .rpyc/.rpymc。

    .rpymc 反编译出来是 .rpym(不是 .rpy),所以配对时按各自的扩展名查,
    否则刚解好的 .rpym 会被当成"还没解"而反复重解。
    """
    game_sub = os.path.join(game_dir, 'game')
    found = []
    for root, dirs, files in os.walk(game_sub):
        names = {f.lower() for f in files}
        for f in files:
            low = f.lower()
            if low.endswith('.rpymc'):
                src_ext = '.rpym'
            elif low.endswith('.rpyc'):
                src_ext = '.rpy'
            else:
                continue
            stem = f.rsplit('.', 1)[0].lower()
            if f'{stem}{src_ext}' not in names:
                found.append(os.path.join(root, f))
    return found


def archive_missing_entries(archive, game_dir):
    """列出压缩包里在游戏目录中还不存在的脚本文件(相对游戏根目录)。"""
    env = dict(os.environ)
    env['PYTHONPATH'] = VENDOR_DIR
    env['PYTHONIOENCODING'] = 'utf-8'
    cmd = [sys.executable, '-m', 'unrpa', '-l', archive]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True,
                       errors='replace', encoding='utf-8')
    if p.returncode != 0:
        return None  # 读不了这个包,交给解包流程去报错
    entries = []
    for line in (p.stdout or '').splitlines():
        line = line.strip()
        if not line or line.startswith(('Extracting', 'Archive', '--')):
            continue
        if not line.lower().endswith(('.rpy', '.rpyc', '.rpym', '.rpymc')):
            continue
        rel = rpa_entry_game_rel(line).replace('/', os.sep)
        if not os.path.exists(os.path.join(game_dir, rel)):
            entries.append(rel)
    return entries


def check_unpacked(game_dir):
    """返回 (是否已解包, 原因说明)。

    只有"包里有东西在游戏目录里看不见"才算未解包 —— 已经解过的包不再重复解,
    否则会覆盖后面生成到 game/tl/ 里的译文。
    """
    need_rpa = []
    for rpa in find_rpa_files(game_dir):
        missing = archive_missing_entries(rpa, game_dir)
        if missing:
            need_rpa.append((rpa, len(missing)))
    if need_rpa:
        return False, f'游戏里还有 {len(need_rpa)} 个 .rpa 包没解开'

    rpycs = find_undecoded_rpyc(game_dir)
    if rpycs:
        return False, f'有 {len(rpycs)} 个 .rpyc 还没有还原成 .rpy'
    return True, ''


def extract_rpa(archive, game_dir):
    """解压到临时目录,只把缺失的脚本文件补进 game/(不覆盖、不解图片音频)。

    游戏本身能直接读 .rpa 里的图片和音频,只有文本需要落成 .rpy 才扫得到;
    全量解压会让游戏体积翻倍,没必要。

    不带 game/ 前缀的包内条目(非标准打包)按引擎语义归入 game/ 下;
    旧版本会把这类条目错解到游戏根目录,这里顺手把逐字节相同的残留副本
    清掉(内容不同的文件可能另有用处,一律保留)。
    """
    import tempfile
    tmp = tempfile.mkdtemp(prefix='kit_unrpa_')
    try:
        env = dict(os.environ)
        env['PYTHONPATH'] = VENDOR_DIR
        env['PYTHONIOENCODING'] = 'utf-8'
        cmd = [sys.executable, '-m', 'unrpa', '-m', '--continue-on-error',
               '-p', tmp, archive]
        p = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           errors='replace', encoding='utf-8')
        out = (p.stdout or '') + (p.stderr or '')

        copied = stale = 0
        legacy_dirs = set()
        for root, dirs, files in os.walk(tmp):
            for f in files:
                if not SCRIPT_EXTS_RE.search(f):
                    continue
                src = os.path.join(root, f)
                raw = os.path.relpath(src, tmp).replace(os.sep, '/')
                rel = rpa_entry_game_rel(raw)
                if rel != raw:
                    legacy = os.path.join(game_dir, raw.replace('/', os.sep))
                    if (os.path.isfile(legacy)
                            and filecmp.cmp(legacy, src, shallow=False)):
                        os.remove(legacy)
                        stale += 1
                        legacy_dirs.add(os.path.dirname(legacy))
                dst = os.path.join(game_dir, rel.replace('/', os.sep))
                if os.path.exists(dst):
                    continue  # 已存在的一律不动
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied += 1
        # 清掉因删除残留而空出来的目录;非空目录 rmdir 会失败,正好当守护
        for d in sorted(legacy_dirs, key=len, reverse=True):
            while d and os.path.normcase(d) != os.path.normcase(game_dir):
                try:
                    os.rmdir(d)
                except OSError:
                    break
                d = os.path.dirname(d)
        return copied, stale, out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_unrpyc(targets):
    cmd = [sys.executable, UNREN, '--clobber', '-p', '4'] + targets
    p = subprocess.run(cmd, capture_output=True, text=True,
                       errors='replace', encoding='utf-8', cwd=os.path.dirname(UNREN))
    return p.returncode == 0, (p.stdout or '') + (p.stderr or '')


def auto_unpack(game_dir, reason):
    """自动解包:先解 rpa,再把 rpyc 反编译回 rpy。

    返回是否真的解出了新东西 —— 决定导出前要不要重新读取语言
    (文本清单可能已经变大,旧的导入是残缺的)。
    """
    banner('这个游戏还没解包，正在自动解包')
    info(f'原因: {reason}')
    print()
    changed = False

    rpas = find_rpa_files(game_dir)
    if rpas:
        info(f'步骤 1/2  解开 {len(rpas)} 个 .rpa 压缩包')
        last_out = ''
        total_stale = 0
        for i, rpa in enumerate(rpas, 1):
            print(f'         [{i}/{len(rpas)}] {os.path.basename(rpa)}')
            copied, stale, last_out = extract_rpa(rpa, game_dir)
            total_stale += stale
            if copied or stale:
                changed = True
        # 解没解开不看返回值, 直接看包里的脚本还在不在游戏目录里
        still = [(r, archive_missing_entries(r, game_dir)) for r in rpas]
        still = [(r, m) for r, m in still if m]
        if still:
            print(last_out[-2000:] if last_out else '')
            die(f'还有 {len(still)} 个压缩包没能解开。',
                '这个包可能加了密或损坏。请改用 UnRen 手动解包:\n'
                'https://github.com/VepsrP/UnRen-Gideon-mod-/releases\n'
                '下载 UnRen-forall.bat 放进游戏目录,双击后按 回车 → 8 → 回车 → y')
        ok(f'{len(rpas)} 个压缩包已解开')
        if total_stale:
            ok(f'清理了 {total_stale} 个旧版本散落在游戏根目录的脚本副本')

    rpycs = find_undecoded_rpyc(game_dir)
    if rpycs:
        info(f'步骤 2/2  把 {len(rpycs)} 个 .rpyc 还原成 .rpy')
        good, out = run_unrpyc(rpycs)
        still = find_undecoded_rpyc(game_dir)
        if still:
            print(out[-2000:] if out else '')
            die(f'还有 {len(still)} 个文件没能还原。',
                '这个游戏可能用了较老或加了混淆的 RenPy 版本。\n'
                '请改用 UnRen 手动解包:\n'
                'https://github.com/VepsrP/UnRen-Gideon-mod-/releases\n'
                '下载 UnRen-forall.bat 放进游戏目录,双击后按 回车 → 8 → 回车 → y')
        ok(f'{len(rpycs)} 个文件已还原')
        changed = True

    print()
    ok('解包完成')
    return changed


# ---------------------------------------------------------------- 工作区

def safe_name(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip() or 'game'


def game_workspace(cfg, game_path):
    ws = os.path.join(cfg['workspace'], safe_name(os.path.basename(game_path)))
    os.makedirs(os.path.join(ws, '待翻译'), exist_ok=True)
    return ws


def read_manifest(ws):
    path = os.path.join(ws, 'manifest.json')
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def write_manifest(ws, data):
    with open(os.path.join(ws, 'manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 索引

def norm(p):
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def find_index(tool, game_path):
    """按游戏路径找已有的索引。"""
    for doc_id, index in tool['TranslationIndex'].list_indexes():
        try:
            if norm(index.project_path) == norm(game_path):
                return doc_id, index
        except Exception:
            continue
    return None, None


def make_nickname(game_path):
    """给游戏起一个索引名。

    英文目录名直接用; 中文/日文等非 ASCII 目录名会被清成空或只剩一两个字,
    这时补一小段路径哈希,避免不同游戏撞成同一个索引名而互相顶掉。
    同一路径始终得到同一个名字,所以重复拖入能认出旧索引。
    """
    base = safe_name(os.path.basename(game_path))
    nick = re.sub(r'[^0-9A-Za-z_\-]', '', base)[:24]
    if len(nick) < 3:
        import hashlib
        digest = hashlib.md5(os.path.normcase(os.path.abspath(game_path)).encode('utf-8'))
        nick = (nick or 'game') + digest.hexdigest()[:8]
    return nick


def ensure_base_injection(tool, index):
    """确认游戏里装着工具需要的支持脚本,缺了就补上。

    工具在生成/导入译文时要靠这份小脚本驱动游戏读文本。用「去掉汉化」
    还原过之后它会被删掉,游戏的索引状态也变成「未注入」,这时再翻译同一个
    游戏就会在这一步失败,所以每次开始前先检查一遍。
    """
    if index.project.get_injection_state('Base'):
        return
    print()
    info('游戏里缺少工具需要的支持脚本(做过还原的游戏是这个状态),正在补上')
    if not run_command(tool, 'ij', f'{index.nickname} -t Base', '安装翻译支持'):
        die('安装翻译支持失败。',
            '请确认游戏目录完整,游戏当前没有在运行,然后重试。')
    # 命令把状态写进了索引库, 手里这个对象还是旧的, 同步一下免得后续判断出错
    index.project.set_injection_state('Base', True)
    ok('翻译支持已就绪')


def ensure_index(tool, cfg, game_path, ws):
    """没有索引就建一个(会启动一次游戏)。"""
    doc_id, index = find_index(tool, game_path)
    if index is not None:
        ok(f'已有翻译索引: {index.nickname}:{index.tag}')
        ensure_base_injection(tool, index)
        return index

    nick = make_nickname(game_path)
    info(f'第一次处理这个游戏，正在建立翻译索引 "{nick}"')
    info('(这一步会启动游戏一次，让游戏自己报告文本清单，窗口弹出后会自动关闭)')
    print()
    if not run_command(tool, 'new', f'"{game_path}" -n {nick}', '建立索引'):
        die('建立索引失败。',
            '请确认这个游戏能正常启动，且目录骨架完整(game/lib/renpy 都在)。')
    print()
    doc_id, index = find_index(tool, game_path)
    if index is None:
        die('索引建立后没能读回来，请重试。')
    ok(f'索引已建立: {index.nickname}:{index.tag}')
    return index


def ensure_lang(tool, index, lang):
    """没导入这个语言就导入一次(会启动一次游戏)。"""
    if index.exists_lang(lang):
        ok(f'语言 "{lang}" 已就绪')
        return
    info(f'第一次使用语言 "{lang}"，正在读取游戏里的文本')
    info('(这一步会启动游戏一次，窗口弹出后会自动关闭)')
    print()
    if not run_command(tool, 'i', f'{index.nickname} -l {lang}', '导入语言'):
        die(f'导入语言 "{lang}" 失败。')
    print()
    ok(f'语言 "{lang}" 已就绪')


# 进度统计口径: 剥掉这些 token 之后还剩文字的行才算「需要翻译」。
# 引擎扫描入库的条目里混着大量无需翻译的东西 —— 纯变量引用([line_1])、
# 富文本标签({#xxx})、占位符(%(name)s)、纯符号数字('...'、'?!')。
# 它们永远不会被导出(引擎导出时同样会过滤), 算进"没翻译"只会吓人。
NOT_TEXT_RE = re.compile(r'\{[^}]*\}|\[[^\]]*\]|%\(.*?\)[sdifx]|%[sdifx]')


def _is_meaningless_text(text):
    """剥掉变量/标签/占位符后没有(或只剩符号数字)正文 -> 无需翻译。"""
    t = NOT_TEXT_RE.sub('', str(text)).strip()
    return (not t) or re.fullmatch(r'[\W_0-9]+', t) is not None


def remaining_counts(tool, index, lang):
    """返回 (已翻译, 未翻译), 只统计确实有文字要翻的行。

    数据库里躺着大量引擎扫进来但无需翻译的条目(纯变量引用、纯符号数字),
    这里把它们剔除 —— 否则"还有 N 行没翻译"会虚高一大截。

    每次都从数据库重新取,因为写译文(lj)之后 stats 已经被更新到 DB,
    而手里这个 index 对象还是旧的,直接读它会报出过期的进度。
    """
    fresh = None
    try:
        fresh = tool['TranslationIndex'].from_docid_or_nickname(
            doc_id=index.doc_id, nickname=index.nickname)
    except Exception:
        fresh = None
    idx = fresh or index
    trans = untrans = 0
    for _, text in idx.get_untranslated_lines(lang, say_only=True):
        if not _is_meaningless_text(text):
            untrans += 1
    for _, text in idx.get_translated_lines(lang, say_only=True):
        if not _is_meaningless_text(text):
            trans += 1
    return trans, untrans


# ---------------------------------------------------------------- 导出

def build_export_args(nickname, lang, out_file, limit=0):
    """拼导出命令。

    limit 为 0(或没配)时不带 --limit,工具就会导出全部未翻译文本;
    只有显式配成 2 以上的行数才限行(工具本身要求 --limit 至少为 2)。
    """
    try:
        limit = int(limit or 0)
    except (TypeError, ValueError):
        limit = 0
    args = f'{nickname} -l {lang} -f "{out_file}" -nw'
    if limit > 1:
        args += f' --limit {limit}'
    return args


def do_export(tool, cfg, game_path):
    lang = cfg['target_language']
    limit = cfg.get('export_limit', 0)
    ws = game_workspace(cfg, game_path)
    manifest = read_manifest(ws)

    banner(f'导出未翻译文本: {os.path.basename(game_path)}')

    unpacked, reason = check_unpacked(game_path)
    unpacked_now = False
    if not unpacked:
        unpacked_now = auto_unpack(game_path, reason)
    else:
        ok('游戏已解包')

    index = ensure_index(tool, cfg, game_path, ws)
    if unpacked_now and index.exists_lang(lang):
        # 解包补进了新的脚本,游戏可见的文本清单已经变大,
        # 之前导入的语言是残缺的,必须重读一遍。
        # (导入会清掉该语言的旧进度再重建;已翻译的内容仍留在
        #  工作区「待翻译」目录里的 *_translated.json 中,可对照重贴。)
        print()
        info('这次解包让游戏多出了新的文本,正在重新读取一遍')
        info('(这一步会启动游戏一次，窗口弹出后会自动关闭)')
        print()
        if not run_command(tool, 'i', f'{index.nickname} -l {lang}', '重新读取语言'):
            die('重新读取语言失败。')
        print()
        ok('文本已重新读取')
    ensure_lang(tool, index, lang)

    trans, untrans = remaining_counts(tool, index, lang)
    print()
    info(f'当前进度: 已翻译 {trans} 行, 未翻译 {untrans} 行')

    batch_no = int(manifest.get('batch', 0)) + 1
    out_dir = os.path.join(ws, '待翻译')
    name = f'{safe_name(os.path.basename(game_path))}_{lang}_{batch_no:03d}.json'
    out_file = os.path.join(out_dir, name)

    banner('正在导出')
    ok_flag = run_command(
        tool, 'sj',
        build_export_args(index.nickname, lang, out_file, limit),
        '导出')
    if not ok_flag:
        die('导出失败。')

    if not os.path.isfile(out_file):
        print()
        ok('没有未翻译的文本了 —— 这个游戏该翻的都翻完了。')
        print()
        info('如果游戏里还看到英文，可能是这些情况:')
        print('         - 那些文本在图片里(不是文本,翻译不了)')
        print('         - 那些文本在脚本里被标记为无需翻译')
        print()
        return

    with open(out_file, encoding='utf-8') as f:
        count = len(json.load(f))

    if count == 0:
        os.remove(out_file)
        print()
        ok('没有未翻译的文本了 —— 这个游戏该翻的都翻完了。')
        print()
        return

    manifest.update({
        'game_path': game_path,
        'game_name': os.path.basename(game_path),
        'nickname': index.nickname,
        'tag': index.tag,
        'lang': lang,
        'batch': batch_no,
    })
    write_manifest(ws, manifest)

    print()
    banner('导出完成')
    ok(f'行数: {count} 行')
    ok(f'文件: {out_file}')
    print()
    print('  接下来把下面这个文件整个丢给对话，让它翻译:')
    print()
    print(f'      {out_file}')
    print()
    print('  翻的时候可以连 翻译提示词.md 的第一段一起发，它会先写翻译任务书再动笔，')
    print('  翻出来的语气和术语更统一。')
    print()
    print('  翻好后，把翻译好的 JSON 拖到 翻译.bat 上，就会自动装回游戏。')
    print()

    if cfg.get('open_folder_after_export', True):
        try:
            subprocess.Popen(['explorer', '/select,', out_file])
        except Exception:
            pass


# ---------------------------------------------------------------- 回填

def load_json_file(path):
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        die(f'这个 JSON 读不了: {os.path.basename(path)} — {e}',
            '请确认拖进来的是一份翻译好的待翻译文件(JSON 格式)。')
    if not isinstance(data, dict) or not data:
        die(f'{os.path.basename(path)} 的内容不是预期的格式。',
            '待翻译文件应该是一个 {编号: 原文} 的 JSON 对象。')
    return data


def discover_part_queue(json_path):
    """拖进来一个翻译好的 part 时, 把同目录里同批的其余 part 一起找出来。

    认两种命名:
    - 引擎导出命名:  <基础名>_<编号>_translated.json (基础名 = 游戏名_语言),
      只组同一基础名下的编号;
    - 通用分块命名:  part<编号>.json / part<编号>_<后缀>.json
      (翻译会话把导出文件拆块翻时常用), 组同目录下所有 part 文件。
    拖入的两者都不是(比如自己改过名)就不组队, 行为与从前一致。
    返回按编号升序的路径列表, 一定包含拖入的那个文件。
    """
    path = os.path.abspath(json_path)
    folder = os.path.dirname(path)
    stem = os.path.splitext(os.path.basename(path))[0]

    m = PART_RE.match(stem)
    if m:
        root = m.group('root').lower()

        def match(s2):
            m2 = PART_RE.match(s2)
            return m2 if m2 and m2.group('root').lower() == root else None
    elif PART_FILE_RE.match(stem):
        def match(s2):
            return PART_FILE_RE.match(s2)
    else:
        return [path]

    found = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return [path]
    for name in names:
        if not name.lower().endswith('.json'):
            continue
        m2 = match(os.path.splitext(name)[0])
        if m2:
            found.setdefault((int(m2.group('num')), name.lower()),
                             os.path.join(folder, name))
    if not found:
        return [path]
    return [found[k] for k in sorted(found)]


def same_file(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def original_export_path(part_path):
    """part 对应当初导出的原文文件(去掉 _translated 后缀); 不在就返回 None。"""
    stem, ext = os.path.splitext(part_path)
    if stem.lower().endswith('_translated'):
        cand = stem[:-len('_translated')] + ext
        if os.path.isfile(cand):
            return cand
    return None


def check_part_fresh(index, lang, part_path):
    """核对 part 的行号清单跟游戏当前文本是否还对得上。

    tid 是按导入批次编的号, 重新读取过语言后旧文件的 tid 会指到别的行,
    直接拖回来会把译文写到错误的行上。旁边还留着当初导出的原文文件时
    可以逐行核对(已翻译的行核对不了也不需要 —— 装回去时引擎会自动丢弃);
    核不出来就放行。返回问题说明, 没问题返回 None。
    """
    orig_file = original_export_path(part_path)
    if orig_file is None:
        return None
    try:
        with open(orig_file, encoding='utf-8') as f:
            orig = json.load(f)
    except Exception:
        return None
    if not isinstance(orig, dict) or not orig:
        return None
    untranslated = dict(index.get_untranslated_lines(lang, say_only=False))
    checked = bad = 0
    for tid, orig_text in orig.items():
        raw = untranslated.get(tid)
        if raw is None:
            continue  # 已翻译(或已不在清单里)的行不判, 装回去时本来就会丢弃
        checked += 1
        if raw != orig_text:
            bad += 1
    if checked and bad:
        return f'{bad}/{checked} 行对不上(原文和游戏当前文本不一致)'
    return None


def do_apply(tool, cfg, json_path):
    queue = discover_part_queue(json_path)
    # 先把队列里所有文件都读一遍做校验: 有一个坏的就整体不写, 免得装一半
    parts = [(p, load_json_file(p)) for p in queue]
    dragged = next(d for p, d in parts if same_file(p, json_path))
    game_path, manifest = locate_game_for_file(tool, cfg, json_path, dragged)
    lang = manifest.get('lang') or cfg['target_language']

    banner(f'装回游戏: {os.path.basename(game_path)}')
    if len(parts) > 1:
        ok(f'发现同批翻译 part 共 {len(parts)} 个, 自动组队一起装:')
        for i, (p, d) in enumerate(parts, 1):
            mark = '   <- 拖入的' if same_file(p, json_path) else ''
            print(f'         [{i}/{len(parts)}] {os.path.basename(p)} ({len(d)} 行){mark}')

    doc_id, index = find_index(tool, game_path)
    if index is None:
        die('这个游戏还没有翻译索引。',
            '请先把游戏目录拖到 翻译.bat 上导出一次,再来回填译文。')

    ok(f'索引: {index.nickname}:{index.tag}   语言: {lang}')
    if not index.exists_lang(lang):
        die(f'索引里没有语言 "{lang}"。',
            '请先把游戏目录拖到 翻译.bat 上导出一次,再来回填译文。')

    # 还原过的游戏会缺少支持脚本,先补上再写译文
    ensure_base_injection(tool, index)

    stale = [(p, msg) for p, _ in parts
             if (msg := check_part_fresh(index, lang, p))]
    if stale:
        lines = ['这些文件的行号清单已经和游戏当前文本对不上(通常是游戏重新读取过文本):']
        lines += [f'  {os.path.basename(p)}: {msg}' for p, msg in stale]
        die('\n'.join(lines),
            '旧文件的行号已失效, 拖回来会写到错误的行上。\n'
            '请把游戏目录重新拖一次 翻译.bat 导出最新文本, 用新文件重新翻译。')

    trans_before, _ = remaining_counts(tool, index, lang)
    for i, (p, d) in enumerate(parts, 1):
        print()
        info(f'[{i}/{len(parts)}] 正在写入 {os.path.basename(p)} ({len(d)} 行)')
        if not run_command(tool, 'lj', f'{index.nickname} -l {lang} -f "{p}"', '写入译文'):
            die(f'写入译文失败: {os.path.basename(p)}',
                '排在前面的 part 已经写入; 修好这个文件后重新拖任意一个 part 即可,\n'
                '已写入的不受影响(装过的行引擎会自动跳过)。')
    trans, untrans = remaining_counts(tool, index, lang)
    print()
    extra = f' (本次新增 {trans - trans_before} 行)' if len(parts) > 1 else ''
    info(f'写入后进度: 已翻译 {trans} 行, 未翻译 {untrans} 行{extra}')

    banner('正在生成游戏可用的翻译文件')
    info('(这一步会启动游戏一次，窗口弹出后会自动关闭)')
    print()
    if not run_command(tool, 'g', f'{index.nickname} -l {lang}', '生成翻译'):
        die('生成翻译失败。')

    banner('正在安装中文显示支持')
    if not run_command(tool, 'ij', f'{index.nickname} -t I18n', '安装中文插件'):
        print()
        fail('中文插件没装上,译文可能显示为方块。')
        print('         (译文本身已经装好了,不影响。)')
    else:
        print()
        ok('中文插件已安装')
        # 游戏侧显示补丁: 字体兜底(防方块) + 运行时翻译桥(让数据驱动
        # 型游戏的动态对话也走翻译)。缺哪个文件游戏都会自动跳过。
        try:
            patched = game_patches.write_display_patches(game_path)
            if patched:
                ok('已安装中文显示补丁: ' + ', '.join(
                    os.path.basename(p) for p in patched))
        except Exception as e:
            fail(f'中文显示补丁写入失败(不影响译文): {e}')

    print()
    banner('完成')
    ok('译文已经装进游戏了')
    if len(parts) > 1:
        ok(f'共装回 {len(parts)} 个翻译 part')
    print()
    print('  进游戏后:按 Ctrl + I 打开语言菜单,选 "简体中文"。')
    print('  如果游戏里没有反应,说明这个游戏需要手动加一个入口按钮,')
    print('  让对话帮忙处理即可。')
    if untrans:
        print()
        print(f'  还有 {untrans} 行没翻译。把游戏目录再拖一次 翻译.bat 重新导出。')
    print()


def locate_game_for_file(tool, cfg, json_path, data):
    """先按工作区认领,认不出就用 tid 在所有索引里比对。"""
    parent = os.path.dirname(os.path.abspath(json_path))
    for _ in range(4):
        manifest = read_manifest(parent) if os.path.isfile(
            os.path.join(parent, 'manifest.json')) else None
        if manifest and manifest.get('game_path'):
            game_path = manifest['game_path']
            if os.path.isdir(game_path):
                return game_path, manifest
            die(f'这份文件属于游戏 "{manifest.get("game_name")}"，但它的目录已经不在了。',
                f'记录的位置: {game_path}')
        nxt = os.path.dirname(parent)
        if nxt == parent:
            break
        parent = nxt

    info('正在识别这份文件属于哪个游戏...')
    tids = [t for t in data.keys() if isinstance(t, str)]
    best, best_score = None, 0
    for doc_id, index in tool['TranslationIndex'].list_indexes():
        try:
            lang = index.translation_state
            for kind in ('dialogue', 'string'):
                for lg in lang.get(kind, {}):
                    tids_known = index.get_untranslated_lines(lg, say_only=False)
                    tids_known += index.get_translated_lines(lg, say_only=False)
                    known = {t for t, _ in tids_known}
                    score = sum(1 for t in tids if t in known)
                    if score > best_score:
                        best, best_score = (index.project_path, lg), score
        except Exception:
            continue

    if best and best_score >= max(1, len(tids) // 2):
        ok(f'识别为: {os.path.basename(best[0])} (语言 {best[1]})')
        return best[0], {'lang': best[1]}

    die('认不出这份文件属于哪个游戏。',
        '请把待翻译文件放在它自己的工作区目录里直接翻译,\n'
        '或者确认这个游戏已经用本工具导出过一次。')


# ---------------------------------------------------------------- 入口

def _print_usage():
    print()
    print('=' * 64)
    print('  RenPy 游戏翻译 —— 拖拽工具包')
    print('=' * 64)
    print()
    print('  把【游戏目录】拖到 翻译.bat 上')
    print('      -> 导出全部未翻译文本')
    print('      (拖游戏的 .exe 文件也行,效果一样)')
    print()
    print('  把【翻译好的 JSON 文件】拖到 翻译.bat 上')
    print('      -> 把译文装回游戏')
    print('      (同目录里同批的其他 part 会自动组队, 一次全部装回)')
    print()
    print('  游戏目录 = 能看到 exe 的那一层(里面还有 game、lib、renpy)')
    print()
    print('  给对话的翻译说明:同目录的 翻译提示词.md (发待翻译文件时一起发)')
    print('  译文自检:python check_translation.py 原文.json 译文.json')
    print()
    print('  详细步骤见同目录的 使用说明.md')
    print()


def main():
    if len(sys.argv) < 2:
        _print_usage()
        return 0

    target = ' '.join(sys.argv[1:]).strip().strip('"').strip()
    if not target:
        _print_usage()
        return 1
    if not os.path.exists(target):
        die(f'这个路径不存在: {target}',
            '路径里有空格时请连同引号一起拖,或把文件复制到简单一点的路径再试。')

    cfg = load_config()
    enter_tool_dir(cfg)
    tool = import_tool()

    if os.path.isdir(target):
        do_export(tool, cfg, validate_game_dir(target))
    else:
        if target.lower().endswith('.exe'):
            # 拖的是游戏 exe 本身:它所在的目录就是游戏目录
            info(f'拖的是 exe,按它所在的目录处理: {os.path.dirname(os.path.abspath(target))}')
            do_export(tool, cfg, validate_game_dir(os.path.dirname(os.path.abspath(target))))
        elif target.lower().endswith('.json'):
            do_apply(tool, cfg, os.path.abspath(target))
        else:
            die(f'不认识这个文件类型: {os.path.basename(target)}',
                '拖游戏目录(或游戏 exe)= 导出未翻译文本\n拖翻译好的 JSON = 装回游戏')

    return 0


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
        fail(f'出了个意外错误: {e}')
        print(traceback.format_exc())
        sys.exit(1)
