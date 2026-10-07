import importlib.util
import os
import shutil
import sys

KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'kit.py')
BASE = os.path.join(os.environ.get('TEMP', '/tmp'), 'kit_test')

spec = importlib.util.spec_from_file_location('kit', KIT)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)

F = lambda *a: os.path.join(BASE, *a)
results = []


def check(label, got, want):
    good = got == want
    results.append(good)
    print(f'{"PASS" if good else "FAIL"}  {label}')
    if not good:
        print(f'        got : {got!r}')
        print(f'        want: {want!r}')


def build_rpa3(path, files, key=0xDEADBEEF):
    """按 RPA-3.0 格式手工打包, 不依赖任何外部样本。

    注意: header 要占在正文最前面, offset 是从文件开头算的,
    所以先把占位 header 放进 body 再记录偏移。
    """
    import pickle
    import zlib
    header_placeholder = b'RPA-3.0 ' + b'0' * 16 + b' ' + b'0' * 8 + b'\n'
    body = bytearray(header_placeholder)
    index = {}
    for name, data in files.items():
        offset = len(body)
        body += data
        index[name.encode()] = [(offset ^ key, len(data) ^ key)]

    index_offset = len(body)
    body += zlib.compress(pickle.dumps(index, protocol=2))

    header = b'RPA-3.0 %016x %08x\n' % (index_offset, key)
    assert len(header) == len(header_placeholder), (len(header), len(header_placeholder))
    body[:len(header)] = header
    with open(path, 'wb') as f:
        f.write(bytes(body))


def _mk_game(root):
    """造一个最小的游戏目录骨架。"""
    for d in ('game', 'lib', 'renpy'):
        os.makedirs(os.path.join(root, d), exist_ok=True)
    open(os.path.join(root, os.path.basename(root) + '.exe'), 'w').close()


def build_fixtures():
    """测试用的假游戏目录每次重建, 免得依赖上一次跑剩下的东西。"""
    shutil.rmtree(BASE, ignore_errors=True)

    # fakegame: 干净的合法游戏
    _mk_game(F('fakegame'))

    # clean: 已解包, rpyc 都有同名 rpy
    _mk_game(F('clean'))
    for n in ('common.rpy', 'common.rpyc', 'script.rpy', 'script.rpyc'):
        open(os.path.join(F('clean', 'game'), n), 'w').close()
    # lib 下的 rpa 不该被当成"未解包"
    open(os.path.join(F('clean', 'lib', 'renpy.rpa')), 'w').close()

    # rpa 存在且里面有缺文件 -> 未解包
    _mk_game(F('packed'))
    rpa = os.path.join(F('packed', 'game'), 'archive.rpa')
    build_rpa3(rpa, {'script.rpy': b'label start:\n    "hi"\n'})

    # 孤儿 rpyc(没有同名 rpy) -> 未解包
    _mk_game(F('rpyconly'))
    open(os.path.join(F('rpyconly', 'game', 'orphan.rpyc')), 'wb').write(b'\x00' * 16)

    # rpymc 反编译出来是 rpym(不是 rpy):
    # 已经解好的 rpym 必须被认成"解完了", 否则会反复重解
    _mk_game(F('rpym'))
    open(os.path.join(F('rpym', 'game', 'common.rpym')), 'w').close()
    open(os.path.join(F('rpym', 'game', 'common.rpymc')), 'wb').write(b'\x00' * 16)
    # 没解过的 rpymc 仍要认出来
    _mk_game(F('rpymbad'))
    open(os.path.join(F('rpymbad', 'game', 'orphan.rpymc')), 'wb').write(b'\x00' * 16)

    # 非法的: 缺 lib/renpy
    os.makedirs(F('fakegame2', 'game'), exist_ok=True)

    # 非法的: 没有 exe
    for d in ('game', 'lib', 'renpy'):
        os.makedirs(F('fakegame3', d), exist_ok=True)


build_fixtures()

print('=== 0. 测试用目录已重建 ===')
check('fakegame 就绪', os.path.isdir(F('fakegame', 'renpy')), True)
check('packed 里有 rpa', os.path.isfile(F('packed', 'game', 'archive.rpa')), True)

print()
print('=== 1. 未解包检测 ===')
check('rpa 里有缺文件 -> 未解包',
      kit.check_unpacked(F('packed'))[0], False)
check('只有孤儿 rpyc -> 未解包',
      kit.check_unpacked(F('rpyconly'))[0], False)
check('干净游戏 -> 已解包',
      kit.check_unpacked(F('clean'))[0], True)
check('假游戏(无 rpa 无 rpyc) -> 已解包',
      kit.check_unpacked(F('fakegame'))[0], True)

print()
print('=== 2. 已解包的干净游戏不该被误判 ===')
# clean game has common.rpy + matching script.rpy
check('同名 rpy 存在则忽略 rpyc',
      len(kit.find_undecoded_rpyc(F('clean'))), 0)
check('lib/renpy 下的 rpa 不算数',
      len(kit.find_rpa_files(F('clean'))), 0)
check('解好的 rpym 不算未解包',
      len(kit.find_undecoded_rpyc(F('rpym'))), 0)
check('没解的 rpymc 仍算未解包',
      len(kit.find_undecoded_rpyc(F('rpymbad'))), 1)

print()
print('=== 3. 配置加载 ===')
os.chdir(F('..'))  # avoid cwd-dependent surprises
cfg = kit.load_config()
check('配置有 tool_dir', 'tool_dir' in cfg, True)
check('配置有 export_limit', 'export_limit' in cfg, True)
check('默认导出全部(不带 --limit)',
      '--limit' in kit.build_export_args('nick', 'schinese', 'o.json'), False)
check('显式限行才带 --limit',
      '--limit 300' in kit.build_export_args('nick', 'schinese', 'o.json', 300), True)
check('非法行数退回全量',
      '--limit' in kit.build_export_args('nick', 'schinese', 'o.json', 'abc'), False)

print()
print('=== 4. 游戏目录校验(应拒绝的) ===')
for bad, label in [
    (F('fakegame', 'game'), '拖了 game 子目录'),
    (F('fakegame2'), '缺 lib/renpy'),
    (F('fakegame3'), '没有 exe'),
]:
    try:
        kit.validate_game_dir(bad)
        check(label + ' -> 拒绝', 'accepted', 'rejected')
    except SystemExit:
        check(label + ' -> 拒绝', 'rejected', 'rejected')

print()
print('=== 5. 合法的游戏目录 ===')
try:
    got = kit.validate_game_dir(F('fakegame'))
    check('含 exe + game/lib/renpy -> 通过', os.path.basename(got), 'fakegame')
except SystemExit:
    check('含 exe + game/lib/renpy -> 通过', 'rejected', 'accepted')

print()
print('=== 6. tid / 工作区命名 ===')
check('safe_name 处理非法字符', kit.safe_name('a<b>c:d/e'), 'a_b_c_d_e')
check('safe_name 空名兜底', kit.safe_name('   '), 'game')
check('make_nickname 保留英文', kit.make_nickname(r'C:/x/MyGame v1.2'), 'MyGamev12')
# 中文名会被清成空/极短, 此时补哈希保证唯一
n1 = kit.make_nickname(r'C:/x/我的游戏A')
n2 = kit.make_nickname(r'C:/x/我的游戏B')
check('中文名补哈希后仍唯一', n1 != n2, True)
check('中文名带哈希后缀', len(n1) == len(n2) and n1[-8:] != n2[-8:], True)
check('同一路径结果稳定', kit.make_nickname(r'C:/x/我的游戏A'), n1)
check('索引名不比原名长', len(n1) <= 32, True)

print()
print('=== 7. 翻译 part 组队发现 ===')
P = F('parts')
os.makedirs(P, exist_ok=True)
def mk(name, content='{}'):
    with open(os.path.join(P, name), 'w', encoding='utf-8') as f:
        f.write(content)
mk('GameA_schinese_001_translated.json')
mk('GameA_schinese_002_translated.json')
mk('GameA_schinese_010_translated.json')
mk('GameA_schinese_003_TRANSLATED.JSON')   # 大写后缀也要认
mk('GameA_schinese_002.json')              # 原文文件, 不入队
mk('GameB_schinese_001_translated.json')   # 别的游戏, 不入队
mk('random.json')                          # 无关文件
mk('GameA_schinese_004_translated.txt')    # 扩展名不对, 不入队

q = kit.discover_part_queue(os.path.join(P, 'GameA_schinese_002_translated.json'))
check('拖 002 -> 组齐 001/002/003/010',
      [os.path.basename(x) for x in q],
      ['GameA_schinese_001_translated.json',
       'GameA_schinese_002_translated.json',
       'GameA_schinese_003_TRANSLATED.JSON',
       'GameA_schinese_010_translated.json'])
check('编号按数字排序(10 排在 3 后面)', os.path.basename(q[-1]),
      'GameA_schinese_010_translated.json')
q = kit.discover_part_queue(os.path.join(P, 'GameA_schinese_002.json'))
check('拖原文文件(无 _translated)不组队', len(q), 1)
q = kit.discover_part_queue(os.path.join(P, 'random.json'))
check('拖改名过的文件不组队', len(q), 1)
q = kit.discover_part_queue(os.path.join(P, 'GameB_schinese_001_translated.json'))
check('别的前缀不混入', [os.path.basename(x) for x in q],
      ['GameB_schinese_001_translated.json'])

print()
print('=== 8. 通用分块命名(part<编号>)组队 ===')
P2 = F('parts2')
os.makedirs(P2, exist_ok=True)
def mk2(name, content='{}'):
    with open(os.path.join(P2, name), 'w', encoding='utf-8') as f:
        f.write(content)
mk2('part01.json')
mk2('part02.json')
mk2('part10.json')
mk2('part00_reused.json')      # 带后缀的也算
mk2('part03_TRANSLATED.JSON')  # 大写也算
mk2('parts.json')              # part 后面不是数字, 不算
mk2('partial.json')            # 同上
mk2('Part07.json')             # 大写 part 也算
mk2('other.json')              # 无关文件

q = kit.discover_part_queue(os.path.join(P2, 'part05.json'))
check('part05 不在也不影响, 组齐全部 part 文件',
      [os.path.basename(x) for x in q],
      ['part00_reused.json', 'part01.json', 'part02.json',
       'part03_TRANSLATED.JSON', 'Part07.json', 'part10.json'])
check('按编号排序(00 在最前, 10 在最后)', os.path.basename(q[-1]), 'part10.json')
q = kit.discover_part_queue(os.path.join(P2, 'other.json'))
check('拖无关文件不组队', len(q), 1)
q = kit.discover_part_queue(os.path.join(P2, 'parts.json'))
check('part 后面不是数字不算 part', len(q), 1)

print()
print('总计: %d/%d 通过' % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
