"""Validate release metadata and tag a clean, green main commit."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
API = 'https://api.github.com/repos/aske312/tg_game'


def metadata(root=ROOT, tag=None):
    version = (root/'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version):
        raise ValueError('Invalid VERSION')
    if tag is not None and tag != 'v'+version:
        raise ValueError('Release tag does not match VERSION')
    changelog = (root/'CHANGELOG.md').read_text(encoding='utf-8')
    section = re.search(r'^## '+re.escape(version)+r'\s*\n(.*?)(?=^## |\Z)', changelog, re.M | re.S)
    if not section or not section[1].strip():
        raise ValueError('Write release notes in CHANGELOG.md before publishing')
    return version, section[1].strip()+'\n'


def github(path):
    request = Request(API+path, headers={'Accept':'application/vnd.github+json', 'User-Agent':'rat-race-release'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def require_green(runs, sha):
    matching = [run for run in runs if run['head_sha'] == sha and run.get('head_branch') == 'main' and run.get('event') == 'push']
    if not matching or matching[0].get('status') != 'completed' or matching[0].get('conclusion') != 'success':
        raise ValueError('The latest Checks run for this main commit must finish successfully before tagging')


def require_newer(version, tags):
    previous = [tuple(map(int, tag[1:].split('.'))) for tag in tags if re.fullmatch(r'v\d+\.\d+\.\d+', tag)]
    if previous and tuple(map(int, version.split('.'))) <= max(previous):
        raise ValueError('VERSION must be greater than existing release tags')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['validate', 'notes', 'tag'])
    parser.add_argument('--tag')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    version, notes = metadata(tag=args.tag)
    if args.command == 'notes':
        if args.output:
            args.output.write_text(notes, encoding='utf-8')
        else:
            print(notes, end='')
    elif args.command == 'tag':
        if git('status', '--porcelain') or git('branch', '--show-current') != 'main':
            raise ValueError('Tag releases from a clean main checkout')
        git('fetch', 'origin', 'main', '--tags')
        require_newer(version, git('tag', '--list', 'v*').splitlines())
        sha = git('rev-parse', 'HEAD')
        if sha != git('rev-parse', 'origin/main'):
            raise ValueError('Push this commit to origin/main and wait for Checks first')
        runs = github('/actions/workflows/checks.yml/runs?head_sha='+sha+'&event=push&per_page=10')['workflow_runs']
        require_green(runs, sha)
        tag = 'v'+version
        git('tag', '-a', tag, '-m', 'Release '+tag)
        git('push', 'origin', 'refs/tags/'+tag)
        print('Tagged '+tag+'. The Release workflow will publish it after all checks pass.')
    else:
        print('Release metadata valid: v'+version)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
