"""构造一个真实的 RPA-3.0 包来测解包流程,并验证不会覆盖已有译文。"""
import importlib.util
import os
import pickle
import shutil
import struct
import sys
import zlib

KIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'kit.py')
BASE = os.path.join(os.environ.get('TEMP', '/tmp'), 'kit_rpa_test')

spec = importlib.util.spec_from_file_location('kit', KIT)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)

results = []


def check(label, got, want):
    good = got == want
    results.append(good)
    print(f'{"PASS" if good else "FAIL"}  {label}')
    if not good:
        print(f'        got : {got!r}')
        print(f'        want: {want!r}')


def build_rpa3(path, files, key=0xDEADBEEF):
    """files: {arcname: bytes}. 返回包内数据。"""
    header_placeholder = b'RPA-3.0 ' + b'0' * 16 + b' ' + b'0' * 8 + b'\n'
    body = bytearray(header_placeholder)
    index = {}
    for name, data in files.items():
        offset = len(body)
        body += data
        index[name.encode()] = [(offset ^ key, len(data) ^ key)]

    offset = len(body)
    index_bytes = zlib.compress(pickle.dumps(index, protocol=2))
    body += index_bytes

    header = b'RPA-3.0 %016x %08x\n' % (offset, key)
    assert len(header) == len(header_placeholder), (len(header), len(header_placeholder))
    body[:len(header)] = header
    with open(path, 'wb') as f:
        f.write(bytes(body))
    return len(index_bytes)


# ---------------------------------------------------------------- 造一个游戏
shutil.rmtree(BASE, ignore_errors=True)
GAME = os.path.join(BASE, 'MyGame')
os.makedirs(os.path.join(GAME, 'game'))
os.makedirs(os.path.join(GAME, 'lib'))
os.makedirs(os.path.join(GAME, 'renpy'))
open(os.path.join(GAME, 'MyGame.exe'), 'wb').close()
open(os.path.join(GAME, 'MyGame.py'), 'w').close()

# 包里放: 2 个 rpy(游戏目录里没有) + 1 个 rpy(游戏目录里已经有旧版本) + 1 个非脚本文件
arc = os.path.join(GAME, 'game', 'archive.rpa')
build_rpa3(arc, {
    'game/script.rpy': b'script from archive\n',
    'game/options.rpy': b'options from archive\n',
    'game/existing.rpy': b'NEW VERSION FROM ARCHIVE\n',
    'game/images/pic.png': b'\x89PNG fake',
})
# existing.rpy 已经在游戏目录里,且内容不同 -> 必须保留游戏里的版本
with open(os.path.join(GAME, 'game', 'existing.rpy'), 'w') as f:
    f.write('OLD game version\n')

print('=== 1. 缺哪些文件 ===')
missing = kit.archive_missing_entries(arc, GAME)
check('能读出包内清单', missing is not None, True)
check('game/script.rpy 被识别为缺失', 'game\\script.rpy' in missing, True)
check('game/options.rpy 被识别为缺失', 'game\\options.rpy' in missing, True)
check('game/existing.rpy 不算缺失(已有)', 'game\\existing.rpy' in missing, False)
check('非脚本文件不算缺失', 'game\\images\\pic.png' in missing, False)

print()
print('=== 2. check_unpacked 判定 ===')
unpacked, reason = kit.check_unpacked(GAME)
check('有缺失文件 -> 判定未解包', unpacked, False)
check('原因里提到 rpa', 'rpa' in reason, True)

print()
print('=== 3. 解包: 只补缺, 不覆盖 ===')
copied, out = kit.extract_rpa(arc, GAME)
check('补了 2 个文件', copied, 2)
check('script.rpy 已补进游戏', os.path.exists(os.path.join(GAME, 'game', 'script.rpy')), True)
check('script.rpy 内容正确',
      open(os.path.join(GAME, 'game', 'script.rpy')).read(), 'script from archive\n')
check('existing.rpy 没有被覆盖',
      open(os.path.join(GAME, 'game', 'existing.rpy')).read(), 'OLD game version\n')
check('图片不解出来(游戏能直接读 rpa 里的图)',
      os.path.exists(os.path.join(GAME, 'game', 'images', 'pic.png')), False)

print()
print('=== 4. 第二次拖入: 不该重复解包 ===')
unpacked, reason = kit.check_unpacked(GAME)
check('文件都在了 -> 判定已解包', unpacked, True)
check('原因应为空', reason, '')

print()
print('=== 5. 回归: 生成的译文不会被覆盖 ===')
# 模拟工具生成译文后, game/tl/schinese/script.rpy 出现
tl = os.path.join(GAME, 'game', 'tl', 'schinese')
os.makedirs(tl, exist_ok=True)
tl_file = os.path.join(tl, 'script.rpy')
with open(tl_file, 'w', encoding='utf-8') as f:
    f.write('translate schinese xxx:\n    "你好"\n')

unpacked, reason = kit.check_unpacked(GAME)
check('有译文时仍判定已解包', unpacked, True)
# 即使强行再解一次, 译文也必须还在
kit.extract_rpa(arc, GAME)
check('译文文件仍在', os.path.exists(tl_file), True)
check('译文内容未被改写',
      '你好' in open(tl_file, encoding='utf-8').read(), True)

print()
print('总计: %d/%d 通过' % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
