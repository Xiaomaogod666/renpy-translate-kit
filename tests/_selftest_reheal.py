"""还原之后还能继续翻译: 检查 kit 会自动补回缺失的支持脚本。

背景: 「去掉汉化」会把 game/projz_injection.rpy 删掉, 并把索引里的
injection_state['Base'] 置为 False。工具在生成/导入译文前会断言 Base 注入
存在, 所以再翻译同一个游戏必须先把这份脚本补回去。

这个测试造一个合成游戏, 摆成「刚被还原过」的样子, 然后调 kit 的
ensure_base_injection, 检查脚本回来了、状态持久化成 True。

跑法:
  <venv>/python.exe tests/_selftest_reheal.py
"""
import importlib.util
import os
import shutil
import sys

KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(os.path.dirname(KIT_DIR), 'projz_renpy_translation')
KIT = os.path.join(KIT_DIR, 'kit.py')
BASE = os.path.join(os.environ.get('TEMP', '/tmp'), 'kit_reheal')

os.chdir(TOOL)
sys.path.insert(0, TOOL)

import log  # noqa: E402,F401
from config import default_config  # noqa: E402
from injection.renpy import Project  # noqa: E402
from store import TranslationIndex  # noqa: E402

spec = importlib.util.spec_from_file_location('kit', KIT)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)

tool_handle = kit.import_tool()

results = []


def check(label, got, want):
    good = got == want
    results.append(good)
    print(f'{"PASS" if good else "FAIL"}  {label}')
    if not good:
        print(f'        got : {got!r}')
        print(f'        want: {want!r}')


# ---------------------------------------------------------------- 造现场
shutil.rmtree(BASE, ignore_errors=True)
GAME = os.path.join(BASE, 'RehealTest')
for d in ('game', 'lib', 'renpy'):
    os.makedirs(os.path.join(GAME, d))
open(os.path.join(GAME, 'RehealTest.exe'), 'w').close()
open(os.path.join(GAME, 'RehealTest.py'), 'w').close()

TOOL_PROJ = os.path.join(BASE, '_projz')
os.makedirs(os.path.join(TOOL_PROJ, 'tmp'), exist_ok=True)
# 沙箱: 把工具的索引目录改到临时目录, 绝不能碰真实的 projz/index.db
if default_config.cfg is None:
    default_config.cfg = {'projz': {}}
default_config.cfg['projz']['project_path'] = TOOL_PROJ
default_config.cfg['projz']['tmp_path'] = os.path.join(TOOL_PROJ, 'tmp')
nick, tag = 'RehealTest', None
assert os.path.abspath(TOOL_PROJ).startswith(os.path.abspath(BASE)), '索引目录必须在沙箱里'
for f in (os.path.join(TOOL_PROJ, 'index.db'), os.path.join(TOOL_PROJ, f'projz_{nick}_{tag}.db')):
    if os.path.exists(f):
        os.remove(f)

# 摆成「刚用 去掉汉化 还原过」: 支持脚本不在, 状态是未注入
injection_file = os.path.join(GAME, 'game', 'projz_injection.rpy')
check('还原后支持脚本不存在', os.path.exists(injection_file), False)

project = Project(project_path=GAME, executable_path=os.path.join(GAME, 'RehealTest.exe'),
                  project_name='RehealTest', game_info={'name': 'RehealTest', 'version': '1.0'},
                  injection_state={'Base': False, 'I18n': False})
index = TranslationIndex(project=project, nickname=nick, tag=tag)
index.save()

print()
print('=== 1. 状态是「未注入」时, 应该去补 ===')
check('补之前状态为假', index.project.get_injection_state('Base'), False)
kit.ensure_base_injection(tool_handle, index)
check('支持脚本被补回来了', os.path.exists(injection_file), True)
check('补之后状态为真', index.project.get_injection_state('Base'), True)

print()
print('=== 2. 从索引重读, 状态应该持久化了 ===')
fresh = TranslationIndex.from_docid_or_nickname(nickname=nick)
check('重读得到索引', fresh is not None, True)
check('重读后状态仍是真', fresh.project.get_injection_state('Base'), True)

print()
print('=== 3. 已经装好的情况下不应重复动作 ===')
mtime_before = os.path.getmtime(injection_file)
kit.ensure_base_injection(tool_handle, fresh)
check('文件没被重写', os.path.getmtime(injection_file), mtime_before)

# 收尾: 关掉缓存的 db 句柄
from store.database.base import _clear_dbs  # noqa: E402
_clear_dbs()

print()
print('总计: %d/%d 通过' % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
