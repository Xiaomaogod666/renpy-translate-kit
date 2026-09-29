#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""译文自检: 回填游戏之前, 检查翻译好的 JSON 有没有会破坏游戏的地方。

用法:
    <venv>/python.exe check_translation.py 原文.json 译文.json
    <venv>/python.exe check_translation.py 原文.json 译文.json --allow-missing
    <venv>/python.exe check_translation.py 原文.json 译文.json --max-show 30

原文 = 工具导出的待翻译文件, 译文 = 翻好后准备拖回 翻译.bat 的文件。
两个文件的编号应该一模一样, 值都是文本。

错误(会和游戏对不上, 必须修):
    编号缺失 / 编号多出     译文少抄或多抄了条目
    值不是文本              值被写成了列表/数字等
    变量丢失 / 不明变量     [pf] 这类方括号变量漏了, 或写成了原文没有的变量名
    标签不一致              {size=24} 这类花括号标签对不上
    换行丢失                字面 \\n 的数量变了
    格式串被改              %A %d 这类给程序读的格式符变了

提示(多半是漏翻或风格问题, 逐条看一眼):
    与原文相同              这行没翻(工具会丢弃它, 留在库里, 下次导出还会出现)
    译文为空                空译文同样会被丢弃, 等于没翻
    整句仍是英文            像是整句没翻
    译文偏长 / 译文偏短     长度和原文差太多
    半角引号                译文中出现半角引号, 一般应写成中文引号
    首尾空格                原文首/尾的空格在译文里不一致(拼接成句的碎片要看)
    编号缺失(--allow-missing)  按批翻译时正常, 收齐后不要再加这个参数

判定尺子取自 001 批已翻好的 300 条基线: 那条基线宽度比最大 1.21,
`[pf]` 出现 1 次变 2 次是合理译法, 所以长度阈值放到 1.4 倍 + 6 宽,
变量只比"名字有没有丢/有没有多", 不比次数。

退出码: 0 = 没有错误, 1 = 有错误, 2 = 文件读不了/用法不对
"""
import json
import os
import re
import sys
from collections import Counter

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors='replace')
    except Exception:
        pass

NL = '\\n'  # 字面两个字符: 反斜杠 + n
VAR_RE = re.compile(r'\[([^\[\]\n]{1,64})\]')
TAG_RE = re.compile(r'\{([^{}\n]{1,64})\}')
FMT_RE = re.compile(r'%[A-Za-z%]')
CJK_RE = re.compile(r'[\u3400-\u9fff]')
LEFTOVER_RE = re.compile(r'\{[^{}]*\}|\[[^\[\]]*\]|%[A-Za-z%]|[^0-9A-Za-z]+')
URL_RE = re.compile(r'https?://|www\.|@[A-Za-z0-9_.-]+\.[A-Za-z]|©|copyright', re.I)
WORD_RE = re.compile(r'[A-Za-z]{2,}')
QUOTE_RE = re.compile(r'"')

ERR_ORDER = ['编号缺失', '编号多出', '值不是文本', '变量丢失', '不明变量',
             '标签不一致', '换行丢失', '格式串被改']
WARN_ORDER = ['与原文相同', '译文为空', '整句仍是英文', '译文偏长', '译文偏短',
              '半角引号', '首尾空格', '编号缺失']

# 长度尺子按 001 批 300 条实测基线放宽: 那条基线宽度比最大 1.21,
# 最小 0.33, 所以只有明显越界才算提示, 免得把正常的意译报成问题。
LONG_SLACK, LONG_ADD = 1.4, 6
SHORT_SLACK, SHORT_MIN_W = 0.25, 40


def width(s):
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def meaningful(s):
    """剥掉变量/标签/格式符后的"实义字母数字", 用来放行 S、{b}、█▓▒░ 这类条目。"""
    return LEFTOVER_RE.sub('', s)


def preview(s, limit=38):
    s = s.replace(NL, '↵')
    return s if len(s) <= limit else s[:limit] + '…'


def compare(src, dst, allow_missing=False):
    errs, warns = {}, {}

    def add(bucket, cat, records):
        """records 可以是单条 4 元组 (编号, 原文, 译文, 说明), 也可以是多条组成的列表。"""
        if isinstance(records, tuple):
            records = [records]
        bucket.setdefault(cat, []).extend(records)

    missing = [k for k in src if k not in dst]
    extra = [k for k in dst if k not in src]
    if missing:
        add(warns if allow_missing else errs, '编号缺失',
            [(k, src[k] if isinstance(src[k], str) else '', '', '') for k in missing])
    if extra:
        add(errs, '编号多出',
            [(k, '', dst[k] if isinstance(dst[k], str) else '', '') for k in extra])

    for tid, s in src.items():
        if tid not in dst:
            continue
        d = dst[tid]
        if not isinstance(s, str) or not isinstance(d, str):
            add(errs, '值不是文本', (tid, repr(s)[:60], repr(d)[:60], ''))
            continue

        sv, dv = VAR_RE.findall(s), VAR_RE.findall(d)
        lost = sorted(set(sv) - set(dv))
        made = sorted(set(dv) - set(sv))
        if lost:
            add(errs, '变量丢失', (tid, s, d, '缺 ' + ' '.join('[' + x + ']' for x in lost)))
        if made:
            add(errs, '不明变量', (tid, s, d, '多出 ' + ' '.join('[' + x + ']' for x in made)))

        st, dt = TAG_RE.findall(s), TAG_RE.findall(d)
        if sorted(st) != sorted(dt):
            miss_t = sorted((Counter(st) - Counter(dt)).elements())
            extra_t = sorted((Counter(dt) - Counter(st)).elements())
            detail = []
            if miss_t:
                detail.append('缺 ' + ' '.join('{' + x + '}' for x in miss_t))
            if extra_t:
                detail.append('多 ' + ' '.join('{' + x + '}' for x in extra_t))
            add(errs, '标签不一致', (tid, s, d, '; '.join(detail)))

        if s.count(NL) != d.count(NL):
            add(errs, '换行丢失', (tid, s, d,
                                f'原文 {s.count(NL)} 个, 译文 {d.count(NL)} 个'))

        sf, df = sorted(FMT_RE.findall(s)), sorted(FMT_RE.findall(d))
        if sf != df:
            add(errs, '格式串被改', (tid, s, d,
                                 f"原文 {' '.join(sf) or '(无)'} -> 译文 {' '.join(df) or '(无)'}"))

        # ------------------------------------------------ 提示
        if d.strip() == '':
            add(warns, '译文为空', (tid, s, d, '空译文会被丢弃, 等于没翻'))
            continue

        if s == d:
            if len(meaningful(s)) >= 2 and not URL_RE.search(s):
                add(warns, '与原文相同', (tid, s, d, ''))
            continue

        if QUOTE_RE.search(d):
            add(warns, '半角引号', (tid, s, d, ''))

        lead = s.startswith(' ') != d.startswith(' ')
        tail = s.endswith(' ') != d.endswith(' ')
        if lead or tail:
            side = '原文' if (s.startswith(' ') or s.endswith(' ')) else '译文'
            add(warns, '首尾空格', (tid, s, d, f'{side}首/尾有空格, 另一边没有'))

        if not URL_RE.search(s) and len(meaningful(s)) >= 2:
            if CJK_RE.search(d) is None and len(WORD_RE.findall(d)) >= 3:
                add(warns, '整句仍是英文', (tid, s, d, ''))
            else:
                ws, wd = width(s), width(d)
                if ws >= 10 and wd > ws * LONG_SLACK + LONG_ADD:
                    add(warns, '译文偏长', (tid, s, d,
                                        f'原文 {ws} 宽, 译文 {wd} 宽, 对话框可能装不下'))
                elif ws >= SHORT_MIN_W and wd < ws * SHORT_SLACK:
                    add(warns, '译文偏短', (tid, s, d,
                                        f'原文 {ws} 宽, 译文只有 {wd} 宽, 可能有整句漏译'))
    return errs, warns


def show_block(title, order, bucket, max_show):
    if not bucket:
        return 0
    total = sum(len(v) for v in bucket.values())
    print(f'—— {title}: {len(bucket)} 类, 共 {total} 条 ——')
    for cat in order:
        items = bucket.get(cat)
        if not items:
            continue
        print(f'  [{cat}] {len(items)} 条')
        for tid, s, d, detail in items[:max_show]:
            line = f'    {tid}'
            if s or d:
                line += f'  {preview(s)}  ->  {preview(d)}'
            if detail:
                line += f'   ({detail})'
            print(line)
        if len(items) > max_show:
            print(f'    ... 还有 {len(items) - max_show} 条')
    return total


def load_json(path):
    try:
        with open(path, encoding='utf-8-sig') as f:
            return json.load(f)
    except Exception as e:
        print(f'读不了这个文件: {path}')
        print(f'    {e}')
        print('    这个文件应该是纯 JSON。如果是从对话复制过来的, 记得去掉外层的')
        print('    ```json 代码块标记, 只留花括号里面的内容。')
        return None


def main(argv):
    pos, allow_missing, max_show = [], False, 15
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--allow-missing':
            allow_missing = True
        elif a == '--max-show':
            i += 1
            if i < len(argv):
                try:
                    max_show = int(argv[i])
                except ValueError:
                    pass
        elif a in ('-h', '--help'):
            print(__doc__)
            return 0
        else:
            pos.append(a)
        i += 1

    if len(pos) != 2:
        print(__doc__)
        return 2

    src_path, dst_path = pos
    src, dst = load_json(src_path), load_json(dst_path)
    if src is None or dst is None:
        return 2
    if not isinstance(src, dict) or not isinstance(dst, dict) or not src:
        print('这两个文件应该是 {编号: 文本} 的 JSON 对象(工具导出的待翻译文件和翻好的文件)。')
        return 2

    print('=== 译文自检 ===')
    print(f'原文: {os.path.basename(src_path)}  ({len(src)} 条)')
    print(f'译文: {os.path.basename(dst_path)}  ({len(dst)} 条)')
    print()

    errs, warns = compare(src, dst, allow_missing)
    n_err = show_block('错误', ERR_ORDER, errs, max_show)
    if n_err:
        print()
    n_warn = show_block('提示', WARN_ORDER, warns, max_show)
    print()
    if n_err:
        print(f'结论: 有错误({n_err} 条), 修好再回填。')
        return 1
    print('结论: 没有发现错误, 可以拖回 翻译.bat。')
    if n_warn:
        print(f'      (另有 {n_warn} 条提示, 逐条看一眼即可。)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
