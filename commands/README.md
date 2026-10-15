# Команды Windows

CMD-файлы можно запускать двойным щелчком. Из корня проекта:

| Команда | Действие |
| --- | --- |
| `commands\start-local.cmd` | Запустить игру локально |
| `commands\start-builder.cmd` | Запустить редактор локально |
| `commands\start-telegram.cmd` | Временный запуск в Telegram через туннель |
| `commands\server.cmd update` | Обновить приложение и редактор на сервере из GitHub |
| `commands\server.cmd status` | Состояние серверных служб |
| `commands\server.cmd logs app --follow` | Журнал приложения |
| `commands\deploy-server.cmd` | Обновить только приложение и бота |

Доступы к серверу и редактору хранятся в приватном `data/builder-server-access.txt`. Настройка окружения описана в [README](../README.md), остальные серверные команды — в [инструкции](../deploy/README.md).
