"""Root-owned local admin service. Accepts only status/update/rollback, no shell input."""
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import subprocess
import threading
import time
import uuid

BASE = Path('/opt/rat-race')
STATE = Path('/var/lib/rat-race-control')
SOCKET = Path('/run/rat-race-control/control.sock')
MANAGER = '/usr/local/sbin/rat-race'
LINKS = {'app': 'current', 'builder': 'builder-current'}
UNITS = ('rat-race-web.service', 'rat-race-bot.service',
         'rat-race-builder.service', 'rat-race-builder-proxy.service')


def release_info(link, base=None):
    base = base or BASE
    path = base/link
    if not path.is_symlink():
        return None
    resolved = path.resolve()
    if resolved.parent != base/'releases' or not re.fullmatch('[0-9a-f]{40}', resolved.name):
        return None
    try:
        version = (resolved/'VERSION').read_text().strip()
    except OSError:
        return None
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        return None
    return dict(version=version, build=resolved.name)


def installed_versions():
    return {name: dict(current=release_info(link), previous=release_info(link+'-previous'))
            for name, link in LINKS.items() if (BASE/link).is_symlink()}


def metrics():
    result = dict(cpu_count=os.cpu_count(), cpu_percent=None, memory=None, uptime=None)
    try:
        def cpu():
            # Guest ticks are already included in user/nice ticks.
            values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
            return sum(values), values[3]+values[4]
        total, idle = cpu()
        time.sleep(.1)
        new_total, new_idle = cpu()
        if new_total > total:
            result['cpu_percent'] = round(100*(1-(new_idle-idle)/(new_total-total)), 1)
        mem = {line.split(':')[0]: int(line.split()[1])*1024
               for line in Path('/proc/meminfo').read_text().splitlines() if line.split()[1].isdigit()}
        result['memory'] = dict(total=mem['MemTotal'], used=mem['MemTotal']-mem['MemAvailable'])
        result['uptime'] = int(float(Path('/proc/uptime').read_text().split()[0]))
    except (OSError, ValueError, KeyError, IndexError):
        pass
    disk = shutil.disk_usage('/var/lib/rat-race' if Path('/var/lib/rat-race').exists() else '/')
    result['disk'] = dict(total=disk.total, used=disk.used, free=disk.free)
    return result


def services():
    result = {}
    for unit in UNITS:
        try:
            process = subprocess.run(['systemctl', 'is-active', unit], capture_output=True, text=True, timeout=2)
            value = process.stdout.strip()
            result[unit] = value if value in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown'
        except (OSError, subprocess.TimeoutExpired):
            result[unit] = 'unknown'
    return result


class Controller:
    def __init__(self, state=STATE):
        self.state = state
        self.state.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.job = None
        try:
            self.job = json.loads((state/'job.json').read_text())
            if self.job['status'] == 'running':
                self.job.update(status='interrupted', finished=time.time())
                self.save()
        except (OSError, ValueError, KeyError):
            self.job = None

    def save(self):
        temporary = self.state/'job.next'
        temporary.write_text(json.dumps(self.job), encoding='utf-8')
        temporary.replace(self.state/'job.json')

    def snapshot(self):
        with self.lock:
            job = dict(self.job) if self.job else None
            if job:
                try:
                    with (self.state/'operation.log').open('rb') as stream:
                        stream.seek(0, 2)
                        stream.seek(max(0, stream.tell()-16000))
                        job['log'] = stream.read().decode('utf-8', errors='replace')
                except OSError:
                    job['log'] = ''
            return job

    def start(self, action):
        if action not in ('update', 'rollback'):
            raise ValueError('Недопустимая операция')
        with self.lock:
            if self.job and self.job['status'] == 'running':
                raise ValueError('Операция уже выполняется. Дождитесь завершения.')
            versions = installed_versions()
            if not versions:
                raise ValueError('Серверная установка не найдена.')
            if action == 'rollback' and not all(v['previous'] and v['previous'] != v['current'] for v in versions.values()):
                raise ValueError('Предыдущая версия доступна не для всех компонентов.')
            self.job = dict(id=uuid.uuid4().hex, action=action, status='running', started=time.time())
            (self.state/'operation.log').write_text('', encoding='utf-8')
            self.save()
            threading.Thread(target=self.run, args=(action,), daemon=True).start()
            return dict(self.job)

    def run(self, action):
        code = -1
        try:
            with (self.state/'operation.log').open('ab', buffering=0) as output:
                process = subprocess.run([MANAGER, action, 'all'], stdout=output, stderr=subprocess.STDOUT,
                                         stdin=subprocess.DEVNULL, start_new_session=True)
                code = process.returncode
        except OSError:
            with (self.state/'operation.log').open('ab') as output:
                output.write(b'Could not run installed server manager.\n')
        finally:
            with self.lock:
                self.job.update(status='succeeded' if code == 0 else 'failed', exit_code=code, finished=time.time())
                self.save()

    def handle(self, request):
        if request == {'action': 'status'}:
            return dict(available=True, metrics=metrics(), services=services(), versions=installed_versions(), job=self.snapshot())
        if request in ({'action': 'update'}, {'action': 'rollback'}):
            return dict(job=self.start(request['action']))
        raise ValueError('Недопустимый запрос')


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        try:
            raw = self.rfile.readline(1025)
            if len(raw) > 1024 or not raw.endswith(b'\n'):
                raise ValueError('Слишком большой запрос')
            result = self.server.controller.handle(json.loads(raw))
        except json.JSONDecodeError:
            result = dict(error='Недопустимый запрос')
        except ValueError as error:
            result = dict(error=str(error))
        except TypeError:
            result = dict(error='Недопустимый запрос')
        except OSError:
            result = dict(error='Служба управления временно недоступна')
        self.wfile.write(json.dumps(result, ensure_ascii=True).encode()+b'\n')


def main():
    controller = Controller()
    SOCKET.unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(str(SOCKET), Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.daemon_threads = True
        server.controller = controller
        server.serve_forever()


if __name__ == '__main__':
    main()
