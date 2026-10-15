"""Public release identification shared by the game, display and builder."""
from functools import lru_cache
from html import escape
import os
from pathlib import Path
import re
import subprocess

APP_VERSION = '0.0.5'
ROOT = Path(__file__).resolve().parent.parent


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
    return Path(path).read_text(encoding='utf-8').replace('__APP_VERSION_LABEL__', escape(version_info()['label']))
