# Развёртывание «Крысиных бегов»

Разработка и тесты выполняются локально. Код передаётся через `https://github.com/aske312/tg_game`, ветка `main`. Сервер получает только закоммиченную версию из GitHub.

## Обновление

Локально:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git add app static tests deploy scripts README.md requirements.txt .env.example .gitignore start-local.cmd start-telegram.cmd
git commit -m "Describe the change"
git push origin main
```

На сервере:

```bash
sudo bash /opt/rat-race/current/deploy/update.sh
```

Скрипт скачивает `main`, создаёт отдельный каталог релиза по SHA, запускает тесты, делает согласованную резервную копию SQLite и переключает `/opt/rat-race/current`. После проверки `/api/health` перезапускается бот. Предыдущие релизы сохраняются. Если новый веб-сервер не отвечает, переключается предыдущий каталог. Зависимости находятся в общей `.venv`; изменения зависимостей требуют отдельной проверки совместимости при откате.

## Постоянные файлы

- `/etc/rat-race/app.env` — токен бота, HTTPS-адрес, настройки (root:root, 600).
- `/etc/rat-race/release.env` — SHA запущенной версии.
- `/var/lib/rat-race/game.sqlite3` — база игры (служба `ratrace`).
- `/var/lib/rat-race/backups/` — резервные копии перед обновлением.
- `/opt/rat-race/repo.git` — зеркало GitHub.
- `/opt/rat-race/releases/<SHA>/` — неизменяемые версии приложения.

Файлы `.env`, `server.txt`, базы и ключи SSH не передаются в GitHub. `scripts/server_admin.py` использует локальный `server.txt`; для него отдельно установите `paramiko` в локальное окружение. Формат: `IP: ...`, `PORT: 22`, `USER: ...`, `PSW: ...`.

## Диагностика

```bash
systemctl status rat-race-web rat-race-bot --no-pager
journalctl -u rat-race-web -u rat-race-bot -n 50 --no-pager
curl -fsS http://127.0.0.1:8010/api/health
systemctl status rat-race-cert-renew.timer --no-pager
```

Сервер запускает один процесс приложения на loopback-порту 8010. HTTPS и WebSocket обслуживает Caddy на 443. Сертификат на IP выпускает Certbot с профилем `shortlived`; systemd-таймер проверяет продление каждые 12 часов. После продления сертификаты копируются в `/etc/rat-race/tls/` с доступом только для Caddy, затем Caddy перезагружает конфигурацию. HTTP-путь `/.well-known/acme-challenge/` используется для подтверждения владения IP.

Бот работает через long polling. Одновременно запускайте только один его экземпляр с одним токеном: локальный `start-telegram.cmd` после переноса на сервер не нужен. Проверять браузерный режим можно через `start-local.cmd`.
