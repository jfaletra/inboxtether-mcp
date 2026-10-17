"""Administrator-owned bootstrap, invoked ONLY by the sanitized -I -S entrypoint.

No SMTP, configuration or application module is loaded before validation. This
cannot defend against a compromised kernel/interpreter/bootstrap; administrators
must establish their ownership before introducing any SMTP credential.
"""
import os
import stat
import sys


def admin_directory(path):
    path = os.path.abspath(path)
    while True:
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
            raise RuntimeError('Untrusted administrator path.')
        if (stat.S_IMODE(info.st_mode) & 0o022) and not (info.st_mode & stat.S_ISVTX):
            raise RuntimeError('Writable administrator path.')
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent


def admin_file(path, runtime_link=False):
    original = os.path.abspath(path)
    admin_directory(os.path.dirname(original))
    info = os.lstat(original)
    if runtime_link and stat.S_ISLNK(info.st_mode):
        if info.st_uid != 0:
            raise RuntimeError('Untrusted interpreter link.')
        original = os.path.realpath(original)
        admin_directory(os.path.dirname(original))
        info = os.lstat(original)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise RuntimeError('Untrusted administrator file.')


def main():
    if not (sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment):
        raise RuntimeError('Isolated, no-site startup is required.')
    # The installed shell launcher supplies exactly this non-secret environment.
    expected = {'PATH': '/usr/bin:/bin', 'LC_ALL': 'C.UTF-8', 'TZ': 'UTC'}
    if dict(os.environ) != expected:
        raise RuntimeError('Use the sanitized sender entrypoint.')
    admin_file(sys.executable, runtime_link=True)
    admin_directory(sys.base_prefix)
    for location in sys.path:
        if not location or not os.path.isabs(location):
            raise RuntimeError('Unsafe Python search path.')
        if os.path.isdir(location):
            admin_directory(location)
        elif os.path.exists(location):
            admin_file(location)
        else:
            # CPython commonly includes a not-yet-installed stdlib ZIP path.
            admin_directory(os.path.dirname(location))
    directory = os.path.dirname(os.path.abspath(__file__))
    for name in ('send_bootstrap.py', 'send_assistant.py', 'send_client.py', 'draft_assistant.py'):
        admin_file(os.path.join(directory, name))
    # Stdlib-only sender: no venv site-packages, .pth files or user-site imports.
    sys.path.insert(0, directory)
    import send_assistant
    send_assistant.main(bootstrap_verified=True)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Trusted sender startup rejected; verify isolated administrator-controlled installation.', file=sys.stderr)
        raise SystemExit(1) from None
