"""Read private server access without printing credentials."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent


def settings(root=ROOT):
    for path in (root / 'data/builder-server-access.txt', root / 'server.txt'):
        if not path.is_file():
            continue
        result = {}
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(IP|PORT|USER|PSW)\s*[:=]\s*(.*?)\s*$', line, re.IGNORECASE)
            if match:
                result[match[1].upper()] = match[2]
        if not result:
            continue  # Older builder access files may contain only web credentials.
        missing = [key for key in ('IP', 'USER', 'PSW') if not result.get(key)]
        if missing:
            raise ValueError('Missing SSH fields in '+path.name+': '+', '.join(missing))
        port_match = re.fullmatch(r'([0-9]+)(?:/SSH|\s+\(SSH\))?', result.get('PORT', '22'), re.IGNORECASE)
        if not port_match:
            raise ValueError('SSH PORT must be an integer from 1 to 65535') from None
        port = int(port_match[1])
        if not 1 <= port <= 65535:
            raise ValueError('SSH PORT must be an integer from 1 to 65535')
        result['PORT'] = port
        return result
    raise FileNotFoundError('Add IP, PORT, USER and PSW to data/builder-server-access.txt')


def save_builder_access(path, site, password):
    """Refresh editor credentials while retaining SSH and other access entries."""
    existing = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    retained = [line for line in existing if not re.match(r'^\s*(Конструктор игр|Пароль)\s*:', line)]
    text = 'Конструктор игр: '+site+'\nПароль: '+password+'\n'
    if any(line.strip() for line in retained):
        text += '\n'+'\n'.join(retained).strip()+'\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
