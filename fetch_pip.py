#!/usr/bin/env python3
"""修复虚拟环境里的 pip —— 安装.bat 在 pip 自升级失败时的兜底。

新建的虚拟环境会带一个老 pip (Python 3.11 自带的是 2023 年的 23.x),
它打包的证书清单在部分网络环境下验不过 HTTPS (公司代理、抓包代理、
镜像站都会出现), 报 SSL: CERTIFICATE_VERIFY_FAILED。老 pip 连不上网
就升不了自己, 于是改用官方 bootstrap: 用标准库下载 get-pip.py
(标准库走系统证书库, 不受老 pip 影响), 再让它把 pip 换成新版。

用法:
    python fetch_pip.py <虚拟环境目录> [get-pip.py 的地址或本地路径]

退出码 0 = 新 pip 可用, 1 = 失败 (原因会打印), 2 = 用法不对。
"""
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from fetch_engine import download    # 同目录的兄弟脚本
except ImportError:
    def download(url, dest, attempts=3):
        """fetch_engine.py 不在旁边时的退路: 一次性下载。"""
        import urllib.request
        print('正在下载: %s' % url, flush=True)
        req = urllib.request.Request(url, headers={'User-Agent': 'renpy-translate-kit'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(dest, 'wb') as f:
                f.write(r.read())
        except Exception as exc:
            return '下载失败: %s' % exc
        return None

DEFAULT_GETPIP = 'https://bootstrap.pypa.io/get-pip.py'


def venv_python(venv):
    if os.name == 'nt':
        return os.path.join(venv, 'Scripts', 'python.exe')
    return os.path.join(venv, 'bin', 'python')


def say(msg):
    print(msg, flush=True)


def die(msg, code=1):
    print('')
    print('[错误] ' + msg, flush=True)
    return code


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return 2

    venv = os.path.abspath(argv[0])
    source = argv[1] if len(argv) > 1 else DEFAULT_GETPIP

    py = venv_python(venv)
    if not os.path.isfile(py):
        return die('虚拟环境里没有 python: %s' % py)

    tmp = tempfile.mkdtemp(prefix='kit_getpip_')
    try:
        if source.lower().startswith(('http://', 'https://')):
            script = os.path.join(tmp, 'get-pip.py')
            err = download(source, script)
            if err:
                return die('%s\n'
                           '  也可以手动下载 %s, 再这样跑:\n'
                           '    python fetch_pip.py "%s" "本地的 get-pip.py"'
                           % (err, source, venv))
        else:
            script = os.path.abspath(source)
            if not os.path.isfile(script):
                return die('找不到本地 get-pip.py: %s' % script)
            say('使用本地 get-pip.py: %s' % script)

        say('正在用 bootstrap 重装 pip ...')
        try:
            rc = subprocess.call([py, script, '--no-warn-script-location',
                                  '--no-cache-dir'], cwd=tmp)
        except OSError as exc:
            return die('调用 %s 失败: %s' % (py, exc))
        if rc != 0:
            return die('bootstrap 返回 %d, pip 没修好。' % rc)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    try:
        out = subprocess.check_output([py, '-m', 'pip', '--version'],
                                      stderr=subprocess.STDOUT)
        say('pip 已就绪: %s' % out.decode('utf-8', 'replace').strip())
    except (OSError, subprocess.CalledProcessError) as exc:
        return die('pip 仍然不可用: %s' % exc)
    return 0


if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except AttributeError:
        pass
    sys.exit(main(sys.argv[1:]))
