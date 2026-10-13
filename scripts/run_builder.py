"""Run the local authoring service, with credentials outside the repository."""
import os
import secrets
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from builder.auth import hash_password


def main():
    config = ROOT / 'data/builder.env'
    access = ROOT / 'data/builder-access.txt'
    if not config.exists():
        password = secrets.token_urlsafe(24)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('BUILDER_PASSWORD_HASH='+hash_password(password)+'\n', encoding='utf-8')
        access.write_text('Local builder: http://127.0.0.1:8124\nPassword: '+password+'\n', encoding='utf-8')
    os.environ.update({k:v for k,v in dotenv_values(config).items() if v is not None})
    print('Конструктор: http://127.0.0.1:8124', flush=True)
    print('Пароль сохранён в data/builder-access.txt', flush=True)
    import uvicorn
    uvicorn.run('builder.main:app', host='127.0.0.1', port=8124)


if __name__ == '__main__':
    main()
