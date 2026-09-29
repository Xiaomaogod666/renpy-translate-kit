#!/usr/bin/env python3
"""下载并解包翻译引擎 (projz_renpy_translation)。

安装.bat 在 `git clone` 不可用或失败时会调用它。只用标准库, 因此在
一个干净的 Python 环境上也能跑。

用法:
    python fetch_engine.py <目标目录> [压缩包地址或本地路径]

    <目标目录>            引擎要放到的位置 (解包后该目录下应有 main.py)
    [压缩包地址或本地路径]  http(s) 地址, 或一个本地 .zip;
                          省略则用引擎上游仓库的压缩包

退出码 0 = 引擎已就绪, 1 = 失败 (原因会打印出来), 2 = 用法不对。
"""
import http.client
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

DEFAULT_ZIP = ('https://codeload.github.com/abse4411/'
               'projz_renpy_translation/zip/refs/heads/devp')


def say(msg):
    print(msg, flush=True)


def die(msg, code=1):
    print('')
    print('[错误] ' + msg, flush=True)
    return code


def _download_once(url, dest):
    """下载一次。成功返回 None, 失败返回原因字符串。"""
    req = urllib.request.Request(url, headers={'User-Agent': 'renpy-translate-kit'})
    total = 0
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, 'wb') as f:
            length = resp.headers.get('Content-Length')
            if length and length.isdigit():
                total = int(length)
            step = 2 * 1024 * 1024
            mark = step
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if got >= mark:
                    mark += step
                    if total:
                        say('  ... %.1f / %.1f MB' % (got / 1048576.0, total / 1048576.0))
                    else:
                        say('  ... %.1f MB' % (got / 1048576.0))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError,
            http.client.HTTPException) as exc:
        # 服务器提前掐断连接时, http.client 抛 IncompleteRead /
        # RemoteDisconnected 这类协议异常, 不算 OSError, 得单独接住。
        return '下载失败: %s: %s' % (type(exc).__name__, exc)
    if got == 0:
        return '下载失败: 收到 0 字节'
    if total and got < total:
        return '下载不完整: 收到 %d 字节, 应有 %d 字节' % (got, total)
    say('  下载完成: %.1f MB' % (got / 1048576.0))
    return None


def _zip_ok(path):
    """确认下载下来的文件是个完整可解的 zip。

    有的代理会把断掉的响应当成完整响应转发, 这一层查不出长度不符,
    只能靠包本身验证。
    """
    if not zipfile.is_zipfile(path):
        return '下载下来的不是完整压缩包'
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
    except (zipfile.BadZipFile, OSError) as exc:
        return '压缩包打不开: %s' % exc
    if bad:
        return '压缩包内容损坏: %s' % bad
    return None


def download(url, dest, attempts=3, verify_zip=False):
    """把 url 下载到 dest, 中途断流或包不完整时重试。

    代理和某些网络会在大文件末尾把连接掐断, 半截包重下一次通常就好了。
    verify_zip=True 时还要确认下下来的确实是个完整 zip (给引擎包用)。
    成功返回 None, 失败返回最后一次的原因。
    """
    say('正在下载: %s' % url)
    err = '未知错误'
    for i in range(1, attempts + 1):
        if i > 1:
            say('  第 %d/%d 次重试 ...' % (i, attempts))
        err = _download_once(url, dest)
        if err is None and verify_zip:
            err = _zip_ok(dest)
        if err is None:
            return None
        if os.path.exists(dest):
            try:
                os.remove(dest)
            except OSError:
                pass
    return err


def extract(zip_path, target):
    """把 zip 解开搬到 target。成功返回 None, 失败返回原因字符串。"""
    tmp = tempfile.mkdtemp(prefix='kit_engine_')
    try:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp)
        except zipfile.BadZipFile as exc:
            return '压缩包读不了: %s' % exc

        entries = os.listdir(tmp)
        src = tmp
        # codeload 的包会多套一层 <仓库名>-<分支> 目录, 剥掉它
        if len(entries) == 1 and os.path.isdir(os.path.join(tmp, entries[0])):
            src = os.path.join(tmp, entries[0])
        if not os.path.isfile(os.path.join(src, 'main.py')):
            return '压缩包里没有 main.py (顶层是: %s)' % (entries or '(空)')

        parent = os.path.dirname(target)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        if os.path.isdir(target):
            os.rmdir(target)          # 只可能是空目录, 非空在前面已拦下
        shutil.move(src, target)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 2

    target = os.path.abspath(argv[0])
    source = argv[1] if len(argv) > 1 else DEFAULT_ZIP

    if os.path.isfile(os.path.join(target, 'main.py')):
        say('引擎已在位: %s' % target)
        return 0
    if os.path.exists(target):
        if not os.path.isdir(target):
            return die('%s 已存在, 而且不是文件夹。' % target)
        if os.listdir(target):
            return die('%s 已存在而且不是空的, 里面又没有 main.py。\n'
                       '  请把它移走或删掉, 再跑一次。' % target)

    tmp = tempfile.mkdtemp(prefix='kit_fetch_')
    try:
        if source.lower().startswith(('http://', 'https://')):
            zip_path = os.path.join(tmp, 'engine.zip')
            err = download(source, zip_path, verify_zip=True)
            if err:
                return die('%s (已重试)\n'
                           '  网络不通时可以先手动下载这个压缩包, 再这样跑:\n'
                           '    python fetch_engine.py "%s" "本地的压缩包路径"' % (err, target))
        else:
            zip_path = os.path.abspath(source)
            if not os.path.isfile(zip_path):
                return die('找不到本地压缩包: %s' % zip_path)
            say('使用本地压缩包: %s' % zip_path)

        err = extract(zip_path, target)
        if err:
            return die(err)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    for need in ('main.py', 'requirements.txt'):
        if not os.path.isfile(os.path.join(target, need)):
            return die('解包后缺少 %s, 引擎不完整。' % need)

    say('引擎已就绪: %s' % target)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:      # Python 3.6 及更早没有 reconfigure
        pass
    sys.exit(main(sys.argv[1:]))
