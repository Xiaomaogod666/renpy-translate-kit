"""关掉游戏里自带的第三方汉化钩子。

它不是「译文」，是一段伪装成剧本的注入代码：游戏启动时它从自己的音频文件里
解出一个 DLL、丢到存档目录（那个 .bin），再挂上 RenPy 的 replace_text 钩子把
每一句话都送给远程服务翻译，顺便弹一个推广弹窗。

本脚本把那两行注入代码删掉，连带让它重编译、清掉它丢下的 .bin。
删掉之后：不再投放 .bin、不再有翻译钩子、不再有弹窗，游戏回到纯原版。

用法（由 关掉第三方汉化.bat 调用）:
    unhook.py <游戏目录>         预览后确认，再执行
    unhook.py <游戏目录> -y      不确认，直接执行
    unhook.py <游戏目录> -n      只看预览，什么都不改

三条同时成立才认，缺一条只报告不动手：
    1. 有一行 exec(__import__("base64").b64decode('...'))
    2. 解出来的源码里带着它自己的标记（_eptvl / replace_text / dl_failed ...）
    3. 能从里面读出它投放的 .bin 文件名
"""
import base64
import importlib.util
import os
import re
import shutil
import sys
import time
import traceback
import zlib

KIT_DIR = os.path.dirname(os.path.abspath(__file__))

# 那行注入：exec(__import__("base64").b64decode('...'))
HOOK_RE = re.compile(
    r'^\s*exec\(\s*__import__\(\s*["\']base64["\']\s*\)\s*\.\s*b64decode\(\s*["\']'
    r'([A-Za-z0-9+/=\s]{40,})["\']')
INIT_RE = re.compile(r'^\s*init\s+python\s*:\s*$')

# 候选标记。钩子把字符串名都藏进了它自己的 _eptvl(...) 异或里，
# 所以要比对的是「展开异或之后」的文本。至少命中两个才算这个钩子
# （一个只是像，两个就基本不会误伤了）。
MARKERS = ('_eptvl', 'dl_failed', 'dl_success',
           '_lmonbsamkcxlcn', '_hvtaepyoxfimd')
# 异或还原：def _eptvl(_a): return ''.join('%c' % (_c ^ 109) for _c in _a)
XOR_KEY = 109

# 编译产物里那段 base64 的开头 —— base64("def _eptvl(") ，用来发现「只有 .rpyc 有钩子」的情况
RPYC_SIG = b'ZGVmIF9lcHR2bCh'

# 运行时缓存，游戏下次启动自己重建
CACHE_FILES = ('bytecode.rpyb', 'pyanalysis.rpyb', 'screens.rpyb')

# 存档目录里本来只会有 .save / persistent，出现 PE 就是外人丢的
PE_MAGIC = b'MZ'

# 钩子用的两个「音频」载体：真正的 mp3 是谁也不是，里面是加密的 DLL 和舞台二代码
CARRIER_HINTS = ('dl_failed.mp3', 'dl_success.mp3')


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
    print('  RenPy 游戏翻译 —— 关掉游戏自带的第三方汉化钩子')
    print('=' * 64)
    print()
    print('  把【游戏目录】拖到 关掉第三方汉化.bat 上')
    print('      -> 删掉伪装成剧本的注入代码、它丢下的 .bin 和编译残留')
    print('      (拖游戏的 .exe 文件也行,效果一样)')
    print()
    print('  执行前会先列出要动哪些行、备份到哪，确认后才动手。')
    print('  这个动作不可逆（除非用备份还原），但删掉的都是外来代码，')
    print('  不是游戏自己的内容，也不会碰存档。')
    print()
    print('  详细说明见同目录的 使用说明.md')
    print()


# ---------------------------------------------------------------- 识别钩子

def _rel(game_path, path):
    try:
        return os.path.relpath(path, game_path)
    except ValueError:
        return path


def decode_exec(line):
    """把 exec 那行里的 base64 解出来，失败返回 None。"""
    m = HOOK_RE.match(line)
    if not m:
        return None
    blob = re.sub(r'\s+', '', m.group(1))
    try:
        return base64.b64decode(blob + '=' * (-len(blob) % 4))
    except Exception:
        return None


def deobfuscate(raw):
    """把 _eptvl([...]) 这种逐字节异或的字符串还原成明文，返回还原后的全文。"""
    if not raw:
        return ''
    text = raw.decode('utf-8', 'replace')
    parts = [text]
    for nums in re.findall(r'_eptvl\(\s*\[([0-9,\s]+)\]\s*\)', text):
        try:
            vals = [int(x) for x in nums.replace(' ', '').split(',') if x != '']
        except ValueError:
            continue
        parts.append(bytes((c ^ XOR_KEY) & 0xFF for c in vals).decode('utf-8', 'replace'))
    return ' '.join(parts)


def is_hook(raw):
    """解出来的源码是不是那个钩子 —— 先还原混淆串，再看标记。"""
    text = deobfuscate(raw)
    if not text:
        return False
    return sum(1 for mk in MARKERS if mk in text) >= 2


def bin_names(raw):
    """从钩子源码里读出它往存档目录投放的 .bin 名字。

    名字藏在自己的异或串里，所以先还原再找。
    """
    return set(re.findall(r'[A-Za-z0-9_\-]{3,64}\.bin', deobfuscate(raw)))


def find_spans(lines):
    """找出要删的行区间。返回 [(start, end, raw)]，索引 0-based，左闭右开。"""
    out = []
    for i, ln in enumerate(lines):
        raw = decode_exec(ln)
        if raw is None:
            continue
        start = i
        # 上一行是 init python: 而且这一行是它唯一的正文 -> 连块头一起删
        if i > 0 and INIT_RE.match(lines[i - 1]):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j >= len(lines) or not lines[j][:1].isspace():
                start = i - 1
        out.append((start, i + 1, raw))
    return out


def rpyc_has_hook(path):
    """编译产物里有没有钩子。.rpyc 是 RPC2 头 + zlib 块。"""
    try:
        with open(path, 'rb') as f:
            data = f.read()
    except OSError:
        return False
    if not data.startswith(b'RENPY RPC2'):
        return RPYC_SIG in data
    pos = 8
    while pos + 12 <= len(data):
        slot, start, length = (int.from_bytes(data[pos + i:pos + i + 4], 'little')
                               for i in (0, 4, 8))
        pos += 12
        if slot == 0:
            break
        if length <= 0 or start + length > len(data):
            continue
        try:
            if RPYC_SIG in zlib.decompress(data[start:start + length]):
                return True
        except zlib.error:
            continue
    return False


# ---------------------------------------------------------------- 只读扫描

def save_directory_name(game_path):
    """游戏把存档放哪: game/options.rpy 里的 config.save_directory。"""
    p = os.path.join(game_path, 'game', 'options.rpy')
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r'config\.save_directory\s*=\s*["\']([^"\']+)["\']', text)
    return m.group(1) if m else None


def save_dirs(game_path):
    dirs = [os.path.join(game_path, 'game', 'saves')]
    name = save_directory_name(game_path)
    if name:
        appdata = os.environ.get('APPDATA')
        if appdata:
            dirs.insert(0, os.path.join(appdata, 'RenPy', name))
    return [d for d in dirs if os.path.isdir(d)]


def peek(path, n=2):
    try:
        with open(path, 'rb') as f:
            return f.read(n)
    except OSError:
        return b''


def scan(game_path):
    """找出钩子、编译残留和它丢下的 .bin。一个字节都不改。"""
    game_dir = os.path.join(game_path, 'game')
    found = {
        'hooks': [],      # [{'path', 'spans', 'names', 'lines'}]
        'suspect': [],    # 有 exec+b64 但不像 / 解不开（只报告）
        'compiled': [],   # 有钩子却没有明文源码的 .rpyc（只报告，得人工处理）
        'cache': [],
        'save_dirs': [],
        'dropped': [],    # [{'path', 'size', 'why'}]
        'carriers': [],
    }

    for root, dirs, files in os.walk(game_dir):
        if CACHE_FILES and os.path.normcase(os.path.basename(root)) == 'cache':
            for name in CACHE_FILES:
                p = os.path.join(root, name)
                if os.path.isfile(p):
                    found['cache'].append(p)
            dirs[:] = []
            continue
        for fn in files:
            low = fn.lower()
            p = os.path.join(root, fn)
            if low.endswith('.rpy') and not low.endswith('.rpym'):
                try:
                    with open(p, encoding='utf-8', errors='replace') as f:
                        lines = f.readlines()
                except OSError:
                    continue
                spans = find_spans(lines)
                if not spans:
                    continue
                raws = [s[2] for s in spans]
                names = set()
                for raw in raws:
                    names |= bin_names(raw)
                if all(is_hook(raw) for raw in raws) and names:
                    found['hooks'].append({'path': p, 'spans': spans,
                                           'names': names, 'lines': len(lines)})
                else:
                    found['suspect'].append({
                        'path': p,
                        'lines': [s[0] + 1 for s in spans],
                        'markers': max((sum(1 for mk in MARKERS
                                            if mk in deobfuscate(raw))
                                        for raw in raws), default=0),
                        'names': sorted(names)})
            elif low.endswith('.rpyc'):
                if rpyc_has_hook(p) and not os.path.isfile(p[:-5] + '.rpy'):
                    found['compiled'].append(p)
            elif fn in CARRIER_HINTS:
                found['carriers'].append(p)

    # 存档目录里那个 PE
    known = set()
    for h in found['hooks']:
        known |= h['names']
    for d in save_dirs(game_path):
        found['save_dirs'].append(d)
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            continue
        for fn in entries:
            if not fn.lower().endswith('.bin'):
                continue
            p = os.path.join(d, fn)
            if not os.path.isfile(p):
                continue
            size = os.path.getsize(p)
            if peek(p) != PE_MAGIC:
                continue
            hit = fn in known
            if hit or size >= 4096:
                found['dropped'].append({
                    'path': p,
                    'size': size,
                    'why': '钩子源码里写着这个名字' if hit else '存档目录里的 PE，不是存档',
                })

    return found


def has_anything(found):
    return bool(found['hooks'] or found['cache'] or found['dropped'])


# ---------------------------------------------------------------- 备份与删除

def backup(backup_root, game_path, found):
    n = 0
    for h in found['hooks']:
        for ext in ('.rpy', '.rpyc'):
            p = h['path'][:-4] + ext
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
    for item in found['dropped']:
        dst = os.path.join(backup_root, '_存档目录', os.path.basename(item['path']))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(item['path'], dst)
        n += 1
    return n


def strip_spans(path, spans):
    """按行区间删掉注入块；写完返回删掉的行数。

    按字节读写，保留原文件的换行风格（这游戏的 .rpy 是 CRLF）。
    """
    with open(path, 'rb') as f:
        text = f.read().decode('utf-8', 'replace')
    lines = text.splitlines(True)
    drop = set()
    for start, end, _ in spans:
        drop.update(range(start, end))
    keep = [ln for i, ln in enumerate(lines) if i not in drop]
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(''.join(keep).encode('utf-8'))
    os.replace(tmp, path)
    return len(lines) - len(keep)


def remove(paths):
    done = 0
    for p in paths:
        try:
            os.remove(p)
            done += 1
        except FileNotFoundError:
            continue
    return done


# ---------------------------------------------------------------- 预览

def show_plan(game_path, found, backup_root):
    kit.banner(f'关掉第三方汉化钩子: {os.path.basename(game_path)}')
    print(f'  游戏目录: {game_path}')
    print()
    print('  将删除 (都已备份):')
    for h in found['hooks']:
        hit = ', '.join('%d-%d' % (s + 1, e) for s, e, _ in h['spans'])
        print(f'    注入    {_rel(game_path, h["path"])} 第 {hit} 行')
        print('            —— 伪装成 init python 的一段注入，会放出下面那个文件')
        for raw in [s[2] for s in h['spans']]:
            names = bin_names(raw)
            if names:
                print('            它投放: ' + ', '.join(sorted(names)))
    for h in found['hooks']:
        rpyc = h['path'][:-4] + '.rpyc'
        if os.path.isfile(rpyc):
            print(f'    编译    {_rel(game_path, rpyc)}  (删掉，游戏会按干净源码重编译)')
    if found['cache']:
        names = ', '.join(os.path.basename(p) for p in found['cache'])
        print(f'    缓存    game\\cache\\{names}   (游戏下次启动自己重建)')
    for item in found['dropped']:
        print(f'    载荷    {item["path"]}')
        print(f'            —— {item["size"]} 字节的 PE 文件（{item["why"]}）')

    print()
    print('  不会动:')
    print('    存档 game\\saves\\ 与 %APPDATA%\\RenPy\\<游戏>\\*.save、persistent')
    print('    游戏自己的剧本、图片、音频、字体')
    if found['carriers']:
        print('    载体    ' + ', '.join(_rel(game_path, p) for p in found['carriers']))
        print('            —— 里面是加密的 DLL，钩子删掉后就是两个死文件，留着无害')
    print()
    if found['suspect']:
        print('  看不太准、没动 (有 exec+base64，但不像这个钩子):')
        for s in found['suspect']:
            print(f'    {_rel(game_path, s["path"])} 第 {s["lines"]} 行'
                  f'  (标记命中 {s["markers"]}/5)')
        print()
    if found['compiled']:
        print('  发现只有编译产物里有钩子、没有明文源码的:')
        for p in found['compiled']:
            print(f'    {_rel(game_path, p)}')
        print('    这类要先用 unrpyc 反编译再改，本脚本不动。')
        print()
    print(f'  备份到: {backup_root}')
    print('  (想反悔就把备份里的文件按原路径复制回去)')
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
                               '_关钩子备份', time.strftime('%Y%m%d-%H%M%S'))

    if not has_anything(found):
        kit.banner(f'{os.path.basename(game_path)} 里没有发现这种钩子')
        print('  没有注入代码，存档目录里也没有它丢的 .bin。')
        print()
        if found['suspect'] or found['compiled']:
            print('  不过下面这些我没把握，你自己看看:')
            for s in found['suspect']:
                print(f'    {_rel(game_path, s["path"])} 第 {s["lines"]} 行')
            for p in found['compiled']:
                print(f'    {_rel(game_path, p)}')
            print()
        return 0

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
    probe = found['hooks'][0]['path']
    try:
        with open(probe, 'r+b'):
            pass
    except OSError:
        kit.die('游戏文件被占用，多半是游戏还开着。',
                '请先完全退出游戏（含启动器窗口），再运行这个脚本。')

    kit.banner('正在备份并移除')
    try:
        n = backup(backup_root, game_path, found)
        kit.ok(f'已备份 {n} 个文件到 {backup_root}')

        for h in found['hooks']:
            nl = strip_spans(h['path'], h['spans'])
            kit.ok(f'{_rel(game_path, h["path"])} 已清干净（删掉 {nl} 行注入）')
            rpyc = h['path'][:-4] + '.rpyc'
            if os.path.isfile(rpyc):
                remove([rpyc])
                kit.ok(f'{_rel(game_path, rpyc)} 已删除（下次启动按干净源码重编译）')

        if found['cache']:
            remove(found['cache'])
            kit.ok('运行时缓存已清除（游戏下次启动自己重建）')

        if found['dropped']:
            for item in found['dropped']:
                remove([item['path']])
                kit.ok(f'已删除它丢下的载荷: {os.path.basename(item["path"])}')
        print()

        left = scan(game_path)
        if has_anything(left):
            kit.fail('还有残留，请把上面的列表发给开发者:')
            for h in left['hooks']:
                print(f'         {_rel(game_path, h["path"])}')
            for p in left['cache']:
                print(f'         {_rel(game_path, p)}')
            for item in left['dropped']:
                print(f'         {item["path"]}')
            print()
            return 1

        kit.banner('完成')
        print('  钩子已经关掉了。下次启动游戏:')
        print('    - 不会再往存档目录丢 .bin')
        print('    - 不会再弹那个汉化组的推广窗')
        print('    - 不会再有任何在线翻译')
        print()
        print(f'  备份: {backup_root}')
        print('  想反悔: 把备份里的 game\\ 按原路径复制回游戏目录，再删掉同名 .rpyc。')
        print()
        print('  想重新用本工具包翻这个游戏: 拖 翻译.bat 走一遍即可，两者互不干扰。')
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
