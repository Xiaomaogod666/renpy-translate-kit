"""check_translation.py 的自测。

合成一批小 JSON, 逐项制造错误/提示, 检查校验器报得对不对。
同时用真实的 001 批(原文 vs 已翻译)做一次端到端: 那一批是人工确认过的
好译文, 校验器必须报 0 错误 0 提示。

跑法:
  <venv>/python.exe tests/_selftest_check.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys

KIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(KIT_DIR, 'check_translation.py')
BASE = os.path.join(os.environ.get('TEMP', '/tmp'), 'kit_check')
V = os.path.join(os.environ.get('TEMP', '/tmp'),
                 'kit_py_check')  # venv python 由外部传入

results = []


def check(label, got, want):
    good = got == want
    results.append(good)
    print(f'{"PASS" if good else "FAIL"}  {label}')
    if not good:
        print(f'        got : {got!r}')
        print(f'        want: {want!r}')


def w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def run(*args):
    p = subprocess.run([PYTHON, CHECK, *args],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    return p.returncode, (p.stdout or '') + (p.stderr or '')


PYTHON = sys.executable
shutil.rmtree(BASE, ignore_errors=True)

# ---------------------------------------------------------------- 导入 compare
spec = importlib.util.spec_from_file_location('check_translation', CHECK)
ct = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ct)


def cats(errs, warns):
    return sorted(errs), sorted(warns)


print('=== 1) 干净的对照: 0 错误 0 提示 ===')
src = {
    'D0_1': 'Get in the car, [pf].',
    'D0_2': '{size=24}That was close.{/size}',
    'D0_3': 'Line one\\nLine two',
    'D0_4': 'See you at %H:%M.',
}
dst = {
    'D0_1': '[pf]，上车。',
    'D0_2': '{size=24}好险。{/size}',
    'D0_3': '第一行\\n第二行',
    'D0_4': '%H:%M 见。',
}
e, wn = ct.compare(src, dst)
check('干净对照无错误', sorted(e), [])
check('干净对照无提示', sorted(wn), [])

# ---------------------------------------------------------------- 2) 各类错误
print()
print('=== 2) 错误项逐个触发 ===')

e, wn = ct.compare({'D0_1': 'Hello there.', 'D0_2': 'Bye.'}, {'D0_1': '你好。'})
check('缺条目 -> 编号缺失', '编号缺失' in e, True)

e, wn = ct.compare({'D0_1': 'Hello there.'}, {'D0_1': '你好。', 'D0_9': '多出来的'})
check('多条目 -> 编号多出', '编号多出' in e, True)

e, wn = ct.compare(
    {'D0_1': 'Hi [pf].'},
    {'D0_1': '嗨。'})
check('变量丢失 -> 变量丢失', '变量丢失' in e, True)

e, wn = ct.compare(
    {'D0_1': 'Hi there.'},
    {'D0_1': '嗨 [pf]。'})
check('凭空变量 -> 不明变量', '不明变量' in e, True)

e, wn = ct.compare(
    {'D0_1': '{size=24}Hi.{/size}'},
    {'D0_1': '嗨。'})
check('标签丢失 -> 标签不一致', '标签不一致' in e, True)

e, wn = ct.compare(
    {'D0_1': 'A\\nB'},
    {'D0_1': '甲 乙'})
check('换行丢失 -> 换行丢失', '换行丢失' in e, True)

e, wn = ct.compare(
    {'D0_1': 'Saved at %H:%M today.'},
    {'D0_1': '今天 H:M 保存。'})
check('格式串被改 -> 格式串被改', '格式串被改' in e, True)

e, wn = ct.compare(
    {'D0_1': 'Hi.', 'D0_2': 'Bye.'},
    {'D0_1': ['嗨'], 'D0_2': '再见。'})
check('值不是文本 -> 值不是文本', '值不是文本' in e, True)

# [pf] 1 变 2 是 001 的真实合法译法, 不能报错
e, wn = ct.compare(
    {'D0_1': 'Once Paige introduced [pf] to the coach, he offered him a tryout.'},
    {'D0_1': 'Paige把[pf]介绍给教练后，他马上给了[pf]一个试训机会。'})
check('变量重复 1->2 不算错', sorted(e), [])

# ---------------------------------------------------------------- 3) 提示项
print()
print('=== 3) 提示项逐个触发(不报错) ===')

e, wn = ct.compare({'D0_1': 'See you tomorrow.'}, {'D0_1': 'See you tomorrow.'})
check('与原文相同 -> 提示', '与原文相同' in wn, True)
check('与原文相同不算错误', sorted(e), [])

e, wn = ct.compare({'D0_1': 'See you tomorrow.'}, {'D0_1': '   '})
check('空译文 -> 提示', '译文为空' in wn, True)

e, wn = ct.compare({'D0_1': 'I will see you at the gym tomorrow morning.'},
                   {'D0_1': 'I will see you at the gym tomorrow morning!'})
check('整句英文 -> 提示', '整句仍是英文' in wn, True)

e, wn = ct.compare({'D0_1': 'A' * 60}, {'D0_1': '啊' * 5})
check('译文偏短 -> 提示', '译文偏短' in wn, True)

e, wn = ct.compare({'D0_1': 'Hello there.'},
                   {'D0_1': '嗨，' + '这是一段过分冗长的扩充台词' * 4})
check('译文偏长 -> 提示', '译文偏长' in wn, True)

e, wn = ct.compare({'D0_1': 'Hi there.'}, {'D0_1': '嗨 "buddy"。'})
check('半角引号 -> 提示', '半角引号' in wn, True)

e, wn = ct.compare({'D0_1': 'Come on. '}, {'D0_1': '别这样。'})
check('首尾空格不一致 -> 提示', '首尾空格' in wn, True)

# 长度尺子: 001 里 (Hm? Jasmine?) -> （嗯？Jasmine？） 是 1.21 倍, 不该报
e, wn = ct.compare({'D0_1': '(Hm? Jasmine?)'}, {'D0_1': '（嗯？Jasmine？）'})
check('1.21 倍不报偏长', '译文偏长' in wn, False)

# 版权/链接行原样保留, 不该报「与原文相同」
e, wn = ct.compare(
    {'D0_1': 'Kinetic Text Tags (c) 2021 https://example.com'},
    {'D0_1': 'Kinetic Text Tags (c) 2021 https://example.com'})
check('版权行原样保留不报相同', '与原文相同' in wn, False)

# 装饰符号/纯符号条目原样保留
e, wn = ct.compare({'D0_1': '█▓▒░▒▓█░▒▓'}, {'D0_1': '█▓▒░▒▓█░▒▓'})
check('装饰图形原样保留不报相同', '与原文相同' in wn, False)
e, wn = ct.compare({'S0_1': 'S'}, {'S0_1': 'S'})
check('单字母条目不报相同', '与原文相同' in wn, False)

# ---------------------------------------------------------------- 4) 命令行
print()
print('=== 4) 命令行行为 ===')
s_path = os.path.join(BASE, 'src.json')
d_path = os.path.join(BASE, 'dst.json')
w(s_path, {'D0_1': 'Hello.', 'D0_2': 'Bye.'})
w(d_path, {'D0_1': '你好。', 'D0_2': '再见。'})
rc, out = run(s_path, d_path)
check('干净文件退出码 0', rc, 0)

w(d_path, {'D0_1': '你好。'})
rc, out = run(s_path, d_path)
check('缺条目退出码 1', rc, 1)
rc, out = run(s_path, d_path, '--allow-missing')
check('--allow-missing 退出码 0', rc, 0)
check('--allow-missing 仍报编号缺失', '编号缺失' in out, True)

rc, out = run(s_path, os.path.join(BASE, 'nope.json'))
check('文件不存在退出码 2', rc, 2)
rc, out = run(s_path)
check('参数不够退出码 2', rc, 2)

w(d_path, 'not a dict')
rc, out = run(s_path, d_path)
check('不是对象退出码 2', rc, 2)

# ---------------------------------------------------------------- 5) 真实语料(有就跑)
print()
print('=== 5) 真实批次端到端 ===')
# 工作区位置由 kit.json 决定(默认在 kit 目录的上一级)，经 kit 解析，不再写死。
# 从工作区里自动找一组「原文 JSON + 已翻译 JSON」来跑, 游戏名不写死; 找不到就跳过。
_kspec = importlib.util.spec_from_file_location('kit', os.path.join(KIT_DIR, 'kit.py'))
_kmod = importlib.util.module_from_spec(_kspec)
_kspec.loader.exec_module(_kmod)
WORKSPACE = _kmod.load_config()['workspace']


def find_real_pair(root):
    if not os.path.isdir(root):
        return None, None
    for dirpath, _dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) != '待翻译':
            continue
        for fn in sorted(filenames):
            if not fn.endswith('.json') or fn.endswith('_已翻译.json'):
                continue
            src = os.path.join(dirpath, fn)
            dst = os.path.join(dirpath, fn[:-5] + '_已翻译.json')
            if os.path.isfile(dst):
                return src, dst
    return None, None


real_src, real_dst = find_real_pair(WORKSPACE)
if real_src and real_dst:
    print(f'  用 {os.path.relpath(real_src, WORKSPACE)}')
    rc, out = run(real_src, real_dst)
    check('真实批次无错误', rc, 0)
    check('真实批次无提示', '提示' not in out.split('结论')[0], True)
else:
    print('SKIP  工作区里没有「原文 + 已翻译」成对的批次, 跳过')

print()
good = sum(1 for r in results if r)
print(f'==== {good}/{len(results)} passed ====')
shutil.rmtree(BASE, ignore_errors=True)
sys.exit(0 if good == len(results) else 1)
