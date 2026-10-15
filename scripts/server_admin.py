"""Private SSH administration; never print connection credentials."""
import argparse
import sys
from pathlib import Path

import paramiko
from server_access import settings

ROOT = Path(__file__).resolve().parent.parent


def connect():
    cfg = settings()
    known = ROOT / 'data/server_known_hosts'
    known.parent.mkdir(exist_ok=True)
    client = paramiko.SSHClient()
    if known.exists():
        client.load_host_keys(str(known))
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    port = cfg['PORT']
    client.connect(cfg['IP'], port=port, username=cfg['USER'], password=cfg['PSW'],
                   look_for_keys=False, allow_agent=False, timeout=15, auth_timeout=15, banner_timeout=15)
    client.save_host_keys(str(known))
    return client


def run_remote(client, command, script=None):
    """Stream merged output so a full stderr pipe cannot deadlock deployment."""
    stdin, stdout, stderr = client.exec_command(command, timeout=1800)
    stdout.channel.set_combine_stderr(True)
    if script is not None:
        stdin.write(script)
        stdin.channel.shutdown_write()
    for line in stdout:
        print(line, end='', flush=True)
    return stdout.channel.recv_exit_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['exec', 'upload', 'download'])
    parser.add_argument('source')
    parser.add_argument('target', nargs='?')
    args = parser.parse_args()
    with connect() as client:
        if args.operation == 'exec':
            script = Path(args.source).read_text(encoding='utf-8')
            sys.exit(run_remote(client, 'bash -s', script))
        with client.open_sftp() as sftp:
            if args.operation == 'upload':
                sftp.put(args.source, args.target)
                sftp.chmod(args.target, 0o600)
            else:
                sftp.get(args.source, args.target)
        print('Transfer completed.')


if __name__ == '__main__':
    try:
        main()
    except (paramiko.SSHException, OSError, KeyError, ValueError) as exc:
        print('SSH operation failed: '+type(exc).__name__, file=sys.stderr)
        sys.exit(1)
