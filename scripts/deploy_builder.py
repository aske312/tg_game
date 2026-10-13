"""Deploy authoring from GitHub main; keep private configuration outside Git."""
import io
import secrets
import shlex
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from dotenv import dotenv_values
import paramiko

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder.auth import hash_password
from server_admin import connect


def main():
    access = ROOT / 'data/builder-server-access.txt'
    with connect() as client:
        with client.open_sftp() as sftp:
            try:
                sftp.stat('/etc/rat-race/builder.env')
            except FileNotFoundError:
                with sftp.open('/etc/rat-race/app.env', 'r') as stream:
                    cfg = dotenv_values(stream=io.StringIO(stream.read().decode('utf-8')))
                url = urlsplit(cfg['APP_URL'])
                host = '['+url.hostname+']' if ':' in url.hostname else url.hostname
                site = urlunsplit(('https',host+':8443','','',''))
                games = cfg.get('GAME_PACKS_DIR') or str(Path(cfg['DATABASE_PATH']).parent/'games').replace('\\','/')
                # Only the conventional isolated app directory is writable in the service.
                if not games.startswith('/var/lib/rat-race/'):
                    raise RuntimeError('Custom GAME_PACKS_DIR needs a matching service ReadWritePaths setting')
                password = secrets.token_urlsafe(24)
                text = '\n'.join(['BUILDER_PASSWORD_HASH='+hash_password(password),
                                  'BUILDER_DATA_DIR=/var/lib/rat-race/builder',
                                  'GAME_PACKS_DIR='+shlex.quote(games),'BUILDER_SITE='+shlex.quote(site),''])
                access.parent.mkdir(parents=True,exist_ok=True)
                access.write_text('Конструктор игр: '+site+'\nПароль: '+password+'\n',encoding='utf-8')
                with sftp.open('/etc/rat-race/builder.env.part','w') as stream:
                    stream.write(text)
                sftp.chmod('/etc/rat-race/builder.env.part',0o600)
                sftp.rename('/etc/rat-race/builder.env.part','/etc/rat-race/builder.env')
                print('Пароль сохранён локально в data/builder-server-access.txt',flush=True)
        command = "git --git-dir=/opt/rat-race/repo.git fetch origin main && git --git-dir=/opt/rat-race/repo.git show FETCH_HEAD:deploy/update_builder.sh | bash"
        stdin, stdout, stderr = client.exec_command(command,timeout=600)
        for line in stdout:
            print(line,end='',flush=True)
        error = stderr.read().decode('utf-8',errors='replace')
        if error:
            print(error,file=sys.stderr)
        return stdout.channel.recv_exit_status()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (paramiko.SSHException,OSError,RuntimeError,KeyError) as error:
        print('Deployment failed: '+type(error).__name__,file=sys.stderr)
        sys.exit(1)
