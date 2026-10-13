"""Deploy the version pushed to GitHub main using private server.txt access."""
import sys
import paramiko
from server_admin import connect


try:
    with connect() as client:
        stdin, stdout, stderr = client.exec_command('bash /opt/rat-race/current/deploy/update.sh', timeout=600)
        for line in stdout:
            print(line, end='', flush=True)
        error = stderr.read().decode('utf-8', errors='replace')
        if error:
            print(error, file=sys.stderr)
        sys.exit(stdout.channel.recv_exit_status())
except (paramiko.SSHException, OSError) as exc:
    print('Deployment connection failed: '+type(exc).__name__, file=sys.stderr)
    sys.exit(1)
