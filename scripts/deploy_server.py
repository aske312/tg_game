"""Compatibility entry point: update the application from GitHub main."""
import sys

import paramiko

from server import main


if __name__ == '__main__':
    try:
        sys.exit(main(['update', 'app']))
    except (paramiko.SSHException, OSError, KeyError, ValueError) as exc:
        print('Deployment failed: '+type(exc).__name__, file=sys.stderr)
        sys.exit(1)
