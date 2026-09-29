"""跑全套自测。

8 套自测各自独立、互不干扰（各自把自己造的数据放进临时目录），
这个脚本只是按顺序跑一遍并汇总，避免手动敲 8 次命令。

跑法:
  <venv>/python.exe tests/run_all.py            # 跑全部
  <venv>/python.exe tests/run_all.py check      # 只跑名字含 check 的
  <venv>/python.exe tests/run_all.py -k rpa     # 同上

退出码 0 = 全绿, 1 = 有失败或跳过, 2 = 环境不对。
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_DIR = os.path.dirname(HERE)
TOOL = os.path.join(os.path.dirname(KIT_DIR), 'projz_renpy_translation')

# 顺序有讲究: 先快后慢, 先纯逻辑后碰引擎。
SUITES = [
    ('core', '_selftest.py', '核心工具: 配置/命名/路径/解包判定'),
    ('check', '_selftest_check.py', '译文自检: 8 类错误 + 9 类提示'),
    ('fetch', '_selftest_fetch.py', '安装辅助: 下载重试/解包/入口校验'),
    ('untranslate', '_selftest_untranslate.py', '还原: 撤掉工具装进游戏的东西'),
    ('unhook', '_selftest_unhook.py', '关第三方钩子: 识别/预览/备份/还原'),
    ('rpa', '_selftest_rpa.py', '解包: RPA-3.0 与 rpyc 流程'),
    ('e2e', '_selftest_e2e.py', '端到端: 导出 -> 翻译 -> 回填 -> 生成'),
    ('reheal', '_selftest_reheal.py', '自愈: 还原之后还能继续翻译'),
]


def find_python():
    """优先用引擎的 venv。

    没有 venv 就没法跑碰引擎的那几套; 这时退回到当前解释器,
    至少纯逻辑的几套还能跑。
    """
    venv = os.path.join(TOOL, '.venv', 'Scripts', 'python.exe')
    if os.path.isfile(venv):
        return venv, True
    return sys.executable, False


def main(argv):
    keyword = None
    for i, a in enumerate(argv):
        if a in ('-k', '--keyword') and i + 1 < len(argv):
            keyword = argv[i + 1]
        elif not a.startswith('-'):
            keyword = a

    py, have_venv = find_python()
    print('=' * 66)
    print('RenPy 翻译工具包 自测')
    print('=' * 66)
    print('解释器 : %s' % py)
    print('引擎   : %s%s' % (TOOL, '' if os.path.isdir(TOOL) else '   [缺失]'))
    if not have_venv:
        print()
        print('注意: 没找到引擎的 .venv, 用当前解释器跑。')
        print('      碰引擎的用例会因为 import 失败而报错 ——')
        print('      先跑一遍 安装.bat, 或者把 projz_renpy_translation 放到平级目录。')
    if keyword:
        print('筛选   : %s' % keyword)
    print()

    picked = [s for s in SUITES if not keyword or keyword in s[0]]
    if not picked:
        print('没有名字匹配 %r 的用例。可选: %s'
              % (keyword, ', '.join(s[0] for s in SUITES)))
        return 2

    failed, passed = [], []
    for name, script, label in picked:
        path = os.path.join(HERE, script)
        print('-' * 66)
        print('>>> %s  (%s)' % (name, label))
        print('-' * 66)
        if not os.path.isfile(path):
            print('MISSING  %s' % path)
            failed.append((name, 'missing'))
            continue
        rc = subprocess.call([py, path], cwd=HERE)
        if rc == 0:
            passed.append(name)
        else:
            failed.append((name, rc))
        print()

    print('=' * 66)
    print('汇总: %d 通过, %d 失败' % (len(passed), len(failed)))
    if passed:
        print('  通过: %s' % ', '.join(passed))
    if failed:
        print('  失败: %s' % ', '.join('%s(rc=%s)' % (n, r) for n, r in failed))
    print('=' * 66)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
