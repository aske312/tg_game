"""Public release identification shared by the game, display and builder."""
from functools import lru_cache
from html import escape
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent.parent
APP_VERSION = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', APP_VERSION):
    raise ValueError('VERSION must contain a release number such as 0.0.6')


@lru_cache(maxsize=1)
def local_build():
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True,
                                text=True, timeout=2, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 'local'


def version_info():
    build = os.getenv('BUILD_SHA') or local_build()
    if not re.fullmatch(r'[0-9a-fA-F]{7,40}', build):
        build = 'local'
    build = build.lower()
    short = build[:7]
    return dict(version=APP_VERSION, build=build, build_short=short,
                label=f'{APP_VERSION} build {short}')


def versioned_html(path):
    info = version_info()
    html = Path(path).read_text(encoding='utf-8').replace('__APP_VERSION_LABEL__', escape(info['label']))
    # Every release/build invalidates first-party assets in all three interfaces.
    return re.sub(r'(/static/[^\s"\'<>?]+\?v=)[^\s"\'<>]+',
                  lambda match: match[1]+info['version']+'-'+info['build_short'], html)
