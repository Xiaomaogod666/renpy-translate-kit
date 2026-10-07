"""造一个真实的索引,跑通 导出 -> 翻译 -> 回填 -> 生成 全链路。

不需要真的启动游戏: 索引由工具自己的 API 写入,Project 也手工构造。
"""
import importlib.util
import os
import shutil
import sys

KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL = os.path.join(os.path.dirname(KIT_DIR), 'projz_renpy_translation')
KIT = os.path.join(KIT_DIR, 'kit.py')
BASE = os.path.join(os.environ.get('TEMP', '/tmp'), 'kit_e2e')

os.chdir(TOOL)
sys.path.insert(0, TOOL)

import log  # noqa: E402
from config import default_config  # noqa: E402
from injection.renpy import Project  # noqa: E402
from store import TranslationIndex  # noqa: E402
from store.database import TranslationDao  # noqa: E402

spec = importlib.util.spec_from_file_location('kit', KIT)
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)

# kit 的运行时句柄(和真跑的时候一样)
tool_handle = kit.import_tool()

results = []


def check(label, got, want):
    good = got == want
    results.append(good)
    print(f'{"PASS" if good else "FAIL"}  {label}')
    if not good:
        print(f'        got : {got!r}')
        print(f'        want: {want!r}')


shutil.rmtree(BASE, ignore_errors=True)
GAME = os.path.join(BASE, 'TestGame')
for d in ('game', 'lib', 'renpy'):
    os.makedirs(os.path.join(GAME, d))
open(os.path.join(GAME, 'TestGame.exe'), 'w').close()
open(os.path.join(GAME, 'TestGame.py'), 'w').close()

# 沙箱: 把工具的索引目录改到临时目录, 绝不能碰真实的 projz/index.db
TOOL_PROJ = os.path.join(BASE, '_projz')
os.makedirs(os.path.join(TOOL_PROJ, 'tmp'), exist_ok=True)
if default_config.cfg is None:
    default_config.cfg = {'projz': {}}
default_config.cfg['projz']['project_path'] = TOOL_PROJ
default_config.cfg['projz']['tmp_path'] = os.path.join(TOOL_PROJ, 'tmp')
nick, tag, lang = 'TestGame', None, 'schinese'

# 清干净, 避免上次残留
assert os.path.abspath(TOOL_PROJ).startswith(os.path.abspath(BASE)), '索引目录必须在沙箱里'
for f in (os.path.join(TOOL_PROJ, 'index.db'), os.path.join(TOOL_PROJ, f'projz_{nick}_{tag}.db')):
    if os.path.exists(f):
        os.remove(f)

# ---------------------------------------------------------- 建索引
project = Project(project_path=GAME, executable_path=os.path.join(GAME, 'TestGame.exe'),
                  project_name='TestGame', game_info={'name': 'TestGame', 'version': '1.0'},
                  injection_state={'Base': True, 'I18n': False})
index = TranslationIndex(project=project, nickname=nick, tag=tag)
index.save()
print(f'索引已建, doc_id={index.doc_id}')

# 写入 5 条对话 + 2 条字符串, 其中 1 条对话已翻译
N = 5
db_file = os.path.join(TOOL_PROJ, f'projz_{nick}_{tag}.db')
blocks = []
for i in range(N):
    blocks.append({'type': 'renpy.ast.Say', 'what': f'Line {i}', 'code': f'    e "Line {i}"',
                   'new_code': '已翻译 Line 0' if i == 0 else None})
with TranslationDao(db_file) as dao:
    dao.add_batch(f'D{lang}', [{'block': blocks}])
    dao.add_batch(f'S{lang}', [{'block': [
        # 字符串块的 type 取 scanstrings 里的类名, what 是原文
        {'type': 'String', 'what': 'Game Title', 'code': None, 'parsed': [], 'new_code': None},
    ]}])
index.update_translation_stats(lang)
print("索引内容:", index.translation_state)

print()
print('=== 1. 未翻译行数 ===')
untrans = index.get_untranslated_lines(lang, say_only=True)
check('5 对话中 4 条未翻译 + 1 字符串', len(untrans), 5)
check('已翻译的那条不在列表里',
      any('已翻译' in t or 'Line 0' == t for _, t in untrans), False)

print()
print('=== 2. 导出 JSON (走 kit 的 do_export) ===')
ws = os.path.join(BASE, 'workspace', nick)
os.makedirs(os.path.join(ws, '待翻译'), exist_ok=True)
out = os.path.join(ws, '待翻译', f'{nick}_batch01.json')

cfg = kit.load_config()
cfg['export_limit'] = 0

# 直接调 kit 底层: 用工具命令导出(默认全量, 不带 --limit)
import command.manage as manage  # noqa: E402
args = kit.build_export_args(nick, lang, out, cfg['export_limit'])
print(f'  $ sj {args}')
manage.execute_cmd('sj', args)
check('导出文件已生成', os.path.exists(out), True)

import json  # noqa: E402
with open(out, encoding='utf-8') as f:
    data = json.load(f)
check('导出 5 条', len(data), 5)
check('tid 格式正确', all(k[0] in 'DS' and '_' in k for k in data), True)
check('原始文本未被改动', data.get('D4_1'), 'Line 4')

print()
print('=== 3. 模拟翻译(只翻前 3 条, 留 2 条) ===')
items = list(data.items())
translated = {}
for i, (tid, text) in enumerate(items[:3]):
    translated[tid] = f'【译】{text}'
for tid, text in items[3:]:
    translated[tid] = text          # 没翻的保持原样 -> 应被 discord 丢弃
with open(out, 'w', encoding='utf-8') as f:
    json.dump(translated, f, ensure_ascii=False, indent=2)

print()
print('=== 4. 回填 (走工具 lj) ===')
before = len(index.get_untranslated_lines(lang, say_only=True))
load_args = f'{nick} -l {lang} -f "{out}"'
print(f'  $ lj {load_args}')
manage.execute_cmd('lj', load_args)
index._doc_id = index.doc_id  # 重新读
after = len(index.get_untranslated_lines(lang, say_only=True))
check('回填后少 3 条', before - after, 3)
check('剩下 2 条待翻', after, 2)

print()
print('=== 5. 第二批只导出剩下的 ===')
out2 = os.path.join(ws, '待翻译', f'{nick}_batch02.json')
manage.execute_cmd('sj', kit.build_export_args(nick, lang, out2, 0))
with open(out2, encoding='utf-8') as f:
    data2 = json.load(f)
check('第二批 2 条', len(data2), 2)
check('已翻译的没有重复出现',
      all(not v.startswith('【译】') for v in data2.values()), True)

print()
print('=== 6. 部分翻译: 未翻的保持原文应被丢弃 ===')
# 第二批里只翻 1 条, 另一条保持原样
items2 = list(data2.items())
partial = {items2[0][0]: f'【译2】{items2[0][1]}', items2[1][0]: items2[1][1]}
with open(out2, 'w', encoding='utf-8') as f:
    json.dump(partial, f, ensure_ascii=False, indent=2)
manage.execute_cmd('lj', f'{nick} -l {lang} -f "{out2}"')
remaining = len(index.get_untranslated_lines(lang, say_only=True))
check('只收下翻了的 1 条', remaining, 1)

print()
print('=== 7. 生成译文 rpy  [跳过] ===')
print('  g 生成译文的动作由游戏进程自己执行, 必须真的启动一次游戏,')
print('  合成的假游戏做不到, 这一步留给真实游戏验证。')
SKIPPED = True

print()
print('=== 8. 剩余行数统计 (必须从 DB 重读, 不能报过期数字) ===')
trans, untrans = kit.remaining_counts(tool_handle, index, lang)
check('已翻译 5 行 (1 原有 + 3 第一批 + 1 第二批)', trans, 5)
check('未翻译 1 行', untrans, 1)

print()
print('=== 9. 全部翻完后归零 ===')
left = index.get_untranslated_lines(lang, say_only=True)
check('还剩 1 条未翻', len(left), 1)
fix = {t: f'【译3】{v}' for t, v in left}
out3 = os.path.join(ws, '待翻译', f'{nick}_batch03.json')
with open(out3, 'w', encoding='utf-8') as f:
    json.dump(fix, f, ensure_ascii=False, indent=2)
manage.execute_cmd('lj', f'{nick} -l {lang} -f "{out3}"')
trans2, untrans2 = kit.remaining_counts(tool_handle, index, lang)
check('未翻译归零', untrans2, 0)
check('已翻译 6 行', trans2, 6)
check('未翻译行为 0', len(index.get_untranslated_lines(lang, say_only=True)), 0)

print()
print('=== 10. 全翻完后导出应该是空的 ===')
out4 = os.path.join(ws, '待翻译', f'{nick}_batch04.json')
manage.execute_cmd('sj', kit.build_export_args(nick, lang, out4, 0))
empty = (not os.path.exists(out4)) or os.path.getsize(out4) <= 2 or open(out4, encoding='utf-8').read().strip() in ('', '{}')
check('没有新文件可导出', empty, True)

print()
print('=== 11. 超过旧上限(300)的行数必须一次全导出 ===')
M = 400
big = []
for i in range(M):
    big.append({'type': 'renpy.ast.Say', 'what': f'Big {i}', 'code': f'    e "Big {i}"',
                'new_code': None})
with TranslationDao(db_file) as dao:
    dao.add_batch(f'D{lang}', [{'block': big}])
index.update_translation_stats(lang)
out5 = os.path.join(ws, '待翻译', f'{nick}_batch05.json')
manage.execute_cmd('sj', kit.build_export_args(nick, lang, out5, 0))
with open(out5, encoding='utf-8') as f:
    data5 = json.load(f)
check(f'{M} 行一次全导出(无 300 上限)', len(data5), M)

print()
print('=== 12. 显式限行(逃生阀)仍然可用 ===')
out6 = os.path.join(ws, '待翻译', f'{nick}_batch06.json')
manage.execute_cmd('sj', kit.build_export_args(nick, lang, out6, 150))
with open(out6, encoding='utf-8') as f:
    data6 = json.load(f)
check('--limit 150 只导出 150 行', len(data6), 150)

print()
print('=== 13. 拖一个 part 自动组队装回(走 kit.do_apply) ===')
# 库里还有 250 行未翻的 Big; 补 6 行新的, 限行导出这 6 行, 切成 3 个 part
M2 = 6
small = []
for i in range(M2):
    small.append({'type': 'renpy.ast.Say', 'what': f'Tiny {i}', 'code': f'    e "Tiny {i}"',
                  'new_code': None})
with TranslationDao(db_file) as dao:
    dao.add_batch(f'D{lang}', [{'block': small}])
index.update_translation_stats(lang)
_, base_untrans = kit.remaining_counts(tool_handle, index, lang)
check('补 6 行后未翻 406 (400 大批次 + 6 新行)', base_untrans, 406)

parts_dir = os.path.join(BASE, 'parts')
os.makedirs(parts_dir, exist_ok=True)
# 导出文件名故意就叫 <root>_101.json —— 它本身就是 101 part 的原文文件
out7 = os.path.join(parts_dir, 'TestGame_schinese_101.json')
manage.execute_cmd('sj', kit.build_export_args(nick, lang, out7, M2))
with open(out7, encoding='utf-8') as f:
    data7 = json.load(f)
check('限行导出 6 行', len(data7), 6)

# 切成 3 个 part: 101 自带原文文件(新鲜度核对应通过), 102/103 不带; 拖中间的 102
items7 = list(data7.items())
for no, chunk in (('101', items7[0:2]), ('102', items7[2:4]), ('103', items7[4:6])):
    with open(os.path.join(parts_dir, f'TestGame_schinese_{no}_translated.json'), 'w',
              encoding='utf-8') as f:
        json.dump({t: f'【队】{v}' for t, v in chunk}, f, ensure_ascii=False, indent=2)

calls = []
_real_rc = kit.run_command
def fake_rc(tool, cmd, args, what):
    calls.append(cmd)
    if cmd in ('g', 'ij'):
        print(f'  [stub] {what}')
        return True
    return _real_rc(tool, cmd, args, what)
kit.run_command = fake_rc
try:
    kit.do_apply(tool_handle, kit.load_config(),
                 os.path.join(parts_dir, 'TestGame_schinese_102_translated.json'))
finally:
    kit.run_command = _real_rc

check('组队 3 个 part, 逐个 lj', calls.count('lj'), 3)
check('生成只跑一次', calls.count('g'), 1)
check('中文插件只装一次', calls.count('ij'), 1)
_, after_queue = kit.remaining_counts(tool_handle, index, lang)
check('6 行全部写入', after_queue, base_untrans - M2)

print()
print('=== 14. 行号失效的 part 必须整体拒绝(一个都不写) ===')
_, untrans_before = kit.remaining_counts(tool_handle, index, lang)
# 挑一个"当前仍未翻译"的行来伪造失效: 原文文件里给的原文和库里对不上
bad_tid, bad_raw = index.get_untranslated_lines(lang, say_only=True)[0]
bad_orig = os.path.join(parts_dir, 'TestGame_schinese_201.json')
bad_part = os.path.join(parts_dir, 'TestGame_schinese_201_translated.json')
with open(bad_orig, 'w', encoding='utf-8') as f:
    json.dump({bad_tid: '故意写错的原文'}, f, ensure_ascii=False)
with open(bad_part, 'w', encoding='utf-8') as f:
    json.dump({bad_tid: '【坏】译文'}, f, ensure_ascii=False)

calls2 = []
def fake_rc2(tool, cmd, args, what):
    calls2.append(cmd)
    if cmd in ('g', 'ij'):
        return True
    return _real_rc(tool, cmd, args, what)
kit.run_command = fake_rc2
rejected = False
try:
    try:
        kit.do_apply(tool_handle, kit.load_config(), bad_part)
    except SystemExit:
        rejected = True
finally:
    kit.run_command = _real_rc
check('失效 part 被拒绝(退出)', rejected, True)
check('拒绝发生在写入之前', calls2.count('lj'), 0)
_, untrans_after = kit.remaining_counts(tool_handle, index, lang)
check('没有写入任何行', untrans_after, untrans_before)

# 收尾: 关掉缓存的 db 句柄, 否则文件被占用删不掉
from store.database.base import _clear_dbs  # noqa: E402
_clear_dbs()

print()
print('总计: %d/%d 通过%s' % (sum(results), len(results), '  (第 7 步跳过)' if SKIPPED else ''))
sys.exit(0 if all(results) else 1)
