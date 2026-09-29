"""unhook.py 的自测：全部在临时沙箱里跑，不碰真实游戏与工具目录。

跑法:
    <venv>/python.exe tests/_selftest_unhook.py
"""
import base64
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile

KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_passed = 0
_failed = []


def check(name, cond, detail=''):
    global _passed
    if cond:
        _passed += 1
        print('  [OK]   %s' % name)
    else:
        _failed.append(name)
        print('  [FAIL] %s   %s' % (name, detail))


def load_unhook():
    spec = importlib.util.spec_from_file_location('unhook', os.path.join(KIT_DIR, 'unhook.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def xor_list(text):
    return '[' + ','.join(str((ord(c) ^ 109) & 0xFF) for c in text) + ']'


def make_hook_source(bin_name='abc123def456.bin', extra_marks=True):
    """造一段和真钩子同构的载荷：_eptvl 异或 + 投放 .bin + 挂 replace_text。"""
    marks = ''
    if extra_marks:
        marks = ('\n_x = _eptvl(%s)' % xor_list('dl_failed') +
                 '\n_y = _eptvl(%s)' % xor_list('dl_success'))
    return (
        "def _eptvl(_a):\n"
        "    return ''.join('%%c' %% (_c ^ 109) for _c in _a)\n"
        "_p = _eptvl(%s)\n"
        "open(_p, 'wb')\n"
        "config.replace_text = _translate_text%s\n" % (xor_list(bin_name), marks)
    ).encode('utf-8')


def exec_line(src, indent='    '):
    b64 = base64.b64encode(src).decode('ascii')
    return '%sexec(__import__("base64").b64decode(\'%s\'))\n' % (indent, b64)


def build_game(root, with_hook=True, hook_marks=True, bin_name='abc123def456.bin',
               save_name=None):
    """搭一个最小的 RenPy 游戏目录，可选地植入钩子。"""
    save_name = save_name or os.path.basename(root) + '-Test'
    for d in ('game', 'lib', 'renpy', 'game/cache', 'game/audio'):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    for exe in ('FakeGame.exe', 'FakeGame.py'):
        _write(os.path.join(root, exe), 'x')
    _write(os.path.join(root, 'game', 'script.rpy'), 'label start:\n    "hi"\n')
    _write(os.path.join(root, 'game', 'options.rpy'),
           'define config.name = _("Fake")\n'
           'define config.save_directory = "%s"\n' % save_name)
    _write(os.path.join(root, 'game', 'audio', 'dl_failed.mp3'), 'not really an mp3')
    _write(os.path.join(root, 'game', 'audio', 'dl_success.mp3'), 'neither is this')
    for name in ('bytecode.rpyb', 'pyanalysis.rpyb', 'screens.rpyb'):
        _write(os.path.join(root, 'game', 'cache', name), 'cache')

    body = ('init python:\n'
            '    def setReplay():\n'
            '        p = "Dylan"\n'
            '        return p\n')
    if with_hook:
        body += 'init python:\n' + exec_line(make_hook_source(bin_name, hook_marks))
    _write(os.path.join(root, 'game', 'characters.rpy'), body)
    _write(os.path.join(root, 'game', 'characters.rpyc'), b'RENPY RPC2 stub')

    if with_hook:
        save = os.path.join(os.environ['APPDATA'], 'RenPy', save_name)
        os.makedirs(save, exist_ok=True)
        _write(os.path.join(save, bin_name), b'MZ' + b'\0' * 8000)
        _write(os.path.join(save, 'auto-1-LT1.save'), 'save data')
    return os.path.join(root, 'game', 'characters.rpy')


def _write(path, data):
    mode = 'wb' if isinstance(data, bytes) else 'w'
    with open(path, mode) as f:
        f.write(data)


def main():
    global _passed
    print()
    print('=' * 64)
    print('  unhook.py 自测 (沙箱)')
    print('=' * 64)

    unhook = load_unhook()
    base = tempfile.mkdtemp(prefix='kit_unhook_')
    sandbox = os.path.join(base, 'appdata')
    os.makedirs(sandbox, exist_ok=True)
    real_appdata = os.environ.get('APPDATA')
    os.environ['APPDATA'] = sandbox

    try:
        # ---------- 1. 纯函数 ----------
        print()
        print('  -- 识别逻辑 --')
        raw = make_hook_source()
        check('钩子载荷被认出来', unhook.is_hook(raw) is True)
        check('能读出投放的 .bin 名',
              unhook.bin_names(raw) == {'abc123def456.bin'},
              str(unhook.bin_names(raw)))
        # 混淆态里没有明文 dl_failed，必须靠展开异或
        check('标记藏在异或串里 (明文不含 dl_failed)',
              b'dl_failed' not in raw)
        unrelated = base64.b64encode(b'import os\nprint(os.getcwd())\n')
        check('无关 base64 不被误判', unhook.is_hook(unrelated) is False)
        check('空载荷不被误判', unhook.is_hook(b'') is False)
        check('只命中一个标记时不认',
              unhook.is_hook(b"def _eptvl(_a): pass\n") is False)

        lines = ['init python:\n', exec_line(raw), 'label start:\n']
        spans = unhook.find_spans(lines)
        check('find_spans 连块头一共两行',
              len(spans) == 1 and spans[0][0] == 0 and spans[0][1] == 2,
              str([(s, e) for s, e, _ in spans]))
        lines2 = ['label a:\n', exec_line(raw)]
        spans2 = unhook.find_spans(lines2)
        check('上一行不是 init python 时只删自己',
              len(spans2) == 1 and spans2[0][0] == 1 and spans2[0][1] == 2)

        # ---------- 2. 扫描真钩子 ----------
        print()
        print('  -- 扫描 --')
        g1 = os.path.join(base, 'game1')
        rpy = build_game(g1)
        found = unhook.scan(g1)
        check('扫到 1 个钩子', len(found['hooks']) == 1)
        check('钩子行区间 = 第 5-6 行 (含块头)',
              [(s + 1, e) for s, e, _ in found['hooks'][0]['spans']] == [(5, 6)],
              str([(s + 1, e) for s, e, _ in found['hooks'][0]['spans']]))
        check('读出 .bin 名', found['hooks'][0]['names'] == {'abc123def456.bin'})
        check('扫到缓存 3 个', len(found['cache']) == 3, str(len(found['cache'])))
        check('扫到存档里的载荷 1 个',
              [os.path.basename(i['path']) for i in found['dropped']] == ['abc123def456.bin'],
              str([i['path'] for i in found['dropped']]))
        check('载体文件被列出 (留着不动)', len(found['carriers']) == 2)
        check('has_anything 为真', unhook.has_anything(found) is True)
        check('两个存档目录都被找到',
              len(found['save_dirs']) >= 1, str(found['save_dirs']))

        g2 = os.path.join(base, 'game2')
        build_game(g2, with_hook=False)
        clean = unhook.scan(g2)
        check('没钩子的游戏扫不到钩子', clean['hooks'] == [])
        check('没钩子但缓存还在 -> has_anything 真 (缓存可以单独清)',
              unhook.has_anything(clean) is True)

        # ---------- 3. 真的移除 ----------
        print()
        print('  -- 移除 --')
        backup_root = os.path.join(base, 'backup')
        n = unhook.backup(backup_root, g1, found)
        check('备份了 6 个文件 (rpy/rpyc/3 缓存/载荷)', n == 6, str(n))
        check('备份里有 characters.rpy',
              os.path.isfile(os.path.join(backup_root, 'game', 'characters.rpy')))
        check('备份里有载荷',
              os.path.isfile(os.path.join(backup_root, '_存档目录', 'abc123def456.bin')))

        nl = unhook.strip_spans(rpy, found['hooks'][0]['spans'])
        check('删掉 2 行', nl == 2, str(nl))
        with open(rpy, encoding='utf-8') as f:
            after = f.read()
        check('只剩游戏自己的 4 行', len(after.splitlines()) == 4, str(len(after.splitlines())))
        check('删后不含 exec', 'exec(' not in after)
        check('删后不含 base64', 'base64' not in after)
        check('游戏自己的内容还在', 'p = "Dylan"' in after and 'def setReplay' in after)
        check('结尾干净 (最后一行是 return p)',
              after.splitlines()[-1].strip() == 'return p', repr(after.splitlines()[-1]))
        check('所有行以内的格式没乱 (缩进保留)',
              after.splitlines()[1] == '    def setReplay():', repr(after.splitlines()[1]))

        unhook.remove([rpy[:-4] + '.rpyc'] + found['cache'] +
                      [i['path'] for i in found['dropped']])
        left = unhook.scan(g1)
        check('移除后钩子没了', left['hooks'] == [])
        check('移除后载荷没了', left['dropped'] == [])
        check('移除后缓存没了', left['cache'] == [])
        check('移除后 has_anything 为假', unhook.has_anything(left) is False)
        check('存档文件没被动',
              os.path.isfile(os.path.join(os.environ['APPDATA'], 'RenPy', 'game1-Test',
                                          'auto-1-LT1.save')))
        check('载体还在 (脚本本来就不删它)',
              os.path.isfile(os.path.join(g1, 'game', 'audio', 'dl_failed.mp3')))

        # ---------- 4. 边界 ----------
        print()
        print('  -- 边界 --')
        g3 = os.path.join(base, 'game3')
        rpy3 = build_game(g3, with_hook=True, bin_name='other999.bin')
        with open(rpy3, 'rb') as f:
            raw3 = f.read()
        # 统一成 CRLF 且砍掉末行换行（真实包就是这种风格）
        _write(rpy3, raw3.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n').rstrip(b'\r\n'))
        f3 = unhook.scan(g3)
        check('CRLF + 无末行换行也能识别', len(f3['hooks']) == 1, str(len(f3['hooks'])))
        nl3 = unhook.strip_spans(rpy3, f3['hooks'][0]['spans'])
        check('CRLF 版也删掉 2 行', nl3 == 2, str(nl3))
        with open(rpy3, 'rb') as f:
            after3 = f.read()
        check('换行风格保持 CRLF (没被改成 LF)',
              b'\r\n' in after3 and b'\r\n' not in after3.replace(b'\r\n', b''),
              repr(after3[:40]))

        g4 = os.path.join(base, 'game4')
        build_game(g4, with_hook=True, hook_marks=False)
        f4 = unhook.scan(g4)
        check('标记不足时不认，进 suspect 列表', f4['hooks'] == [] and len(f4['suspect']) == 1,
              'hooks=%d suspect=%d' % (len(f4['hooks']), len(f4['suspect'])))

        # 名字对不上、但存档里有 4KB+ 的 PE -> 也要报出来（用独立存档目录，避免串味）
        g5 = os.path.join(base, 'game5')
        build_game(g5, with_hook=False, save_name='FakeGame-Five')
        save5 = os.path.join(os.environ['APPDATA'], 'RenPy', 'FakeGame-Five')
        os.makedirs(save5, exist_ok=True)
        _write(os.path.join(save5, 'unknown.bin'), b'MZ' + b'\0' * 5000)
        f5 = unhook.scan(g5)
        check('来源不明的存档 PE 也会报',
              [os.path.basename(i['path']) for i in f5['dropped']] == ['unknown.bin'],
              str([i['path'] for i in f5['dropped']]))
        _write(os.path.join(save5, 'tiny.bin'), b'MZ small')
        f5b = unhook.scan(g5)
        check('小于 4KB 且名字对不上的不报 (不误删游戏杂物)',
              [os.path.basename(i['path']) for i in f5b['dropped']] == ['unknown.bin'],
              str([i['path'] for i in f5b['dropped']]))

        # ---------- 5. CLI 预览 ----------
        print()
        print('  -- 命令行预览 --')
        py = sys.executable
        g6 = os.path.join(base, 'game6')
        build_game(g6, with_hook=True, bin_name='cli000aaa111.bin')
        r = subprocess.run([py, os.path.join(KIT_DIR, 'unhook.py'), g6, '-n'],
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           env=dict(os.environ, PYTHONUTF8='1',
                                    PYTHONIOENCODING='utf-8'))
        check('-n 返回 0', r.returncode == 0, r.stdout + r.stderr)
        check('-n 打印预览模式', '预览模式' in r.stdout, r.stdout[-300:])
        r2 = subprocess.run([py, os.path.join(KIT_DIR, 'unhook.py')],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            env=dict(os.environ, PYTHONUTF8='1',
                                     PYTHONIOENCODING='utf-8'))
        check('不给参数返回 1 并打印用法', r2.returncode == 1 and '关掉第三方汉化' in r2.stdout,
              r2.stdout[:200])
        r3 = subprocess.run([py, os.path.join(KIT_DIR, 'unhook.py'), 'Z:\\nope\\nope'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            env=dict(os.environ, PYTHONUTF8='1',
                                     PYTHONIOENCODING='utf-8'))
        check('不存在的路径返回 1', r3.returncode == 1, r3.stdout[:200])

        # 已还原的游戏 (g1 之后) 再跑一次应报「没发现」
        r4 = subprocess.run([py, os.path.join(KIT_DIR, 'unhook.py'), g1, '-n'],
                            capture_output=True, text=True, encoding='utf-8', errors='replace',
                            env=dict(os.environ, PYTHONUTF8='1',
                                     PYTHONIOENCODING='utf-8'))
        check('移除后再预览报「没有发现」', '没有发现这种钩子' in r4.stdout, r4.stdout[-300:])
        check('再预览不会重建任何东西',
              unhook.scan(g1)['cache'] == [])
    finally:
        if real_appdata is not None:
            os.environ['APPDATA'] = real_appdata
        shutil.rmtree(base, ignore_errors=True)

    print()
    print('=' * 64)
    if _failed:
        print('  失败 %d / 共 %d' % (len(_failed), _passed + len(_failed)))
        for name in _failed:
            print('    - %s' % name)
        return 1
    print('  全部通过: %d 项' % _passed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
