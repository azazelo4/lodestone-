# Развёртывание Lodestone в Kubernetes

Пошаговый план: от пустого репозитория до работающего трекера с входом через Active Directory. English version: [deploy-kubernetes.md](deploy-kubernetes.md).

## Что получится

```
              Ingress (TLS)
                   │
            Service :80 → :8000
                   │
   Deployment lodestone (2 пода)            Deployment lodestone-worker (по желанию)
   ├─ init: migrate (alembic upgrade head)  └─ рассылка писем и сообщений в мессенджеры
   └─ app: uvicorn, API + веб-интерфейс
                   │
             PostgreSQL 14+ (вне чарта)
                   │
   AD/LDAP · SSO (OIDC) · SMTP · Jira/Plane/Confluence для импорта
```

Чарт `deploy/helm/lodestone` ставит Deployment, Service, Ingress, ConfigMap и, если не задан `existingSecret`, Secret. Базу данных чарт не ставит: используйте управляемый PostgreSQL, отдельный кластер или оператор (CloudNativePG, Zalando).

## Что нужно заранее

| Что | Зачем |
|---|---|
| Kubernetes 1.25+ и `kubectl` с правами на свой namespace | Сам кластер |
| Helm 3.12+ | Установка чарта |
| Ingress-контроллер (ingress-nginx или другой) | Доступ снаружи |
| cert-manager или готовый TLS-сертификат | HTTPS: cookie сессии ставится только по HTTPS |
| PostgreSQL 14+ | Данные |
| Реестр образов: GHCR, Harbor, Nexus | Образ приложения |
| Сервисная учётка AD и корневой сертификат CA (для LDAPS) | Вход через AD |
| DNS-имя, например `tracker.corp.local` | Адрес трекера |

## Шаг 1. Залить код в репозиторий

В архиве `lodestone-repo.zip` лежит готовый git-репозиторий с полной историей коммитов. В `lodestone.bundle` лежит та же история одним файлом.

```bash
unzip lodestone-repo.zip && cd lodestone
git log --oneline                      # 11 коммитов, ветка main, тег v0.1.0
git remote add origin git@github.com:<you>/lodestone.git
git push -u origin main
git push origin v0.1.0
```

Если репозиторий на GitHub, CI (`.github/workflows/ci.yml`) запускает тесты бэкенда на PostgreSQL, проверку типов и сборку фронтенда, а также `helm lint`. После этого он собирает образ:

- при пуше в `main` публикуются теги `ghcr.io/<you>/lodestone:latest` и `sha-…`;
- при пуше тега `v0.1.0` публикуется тег `ghcr.io/<you>/lodestone:0.1.0`.

По умолчанию чарт берёт тег образа из `appVersion` (0.1.0), поэтому тег `v0.1.0` нужно запушить.

## Шаг 2. Сделать образ доступным кластеру

**Вариант А, GHCR.** Пакет, который создаёт CI, по умолчанию приватный. Есть два пути.
- Сделайте его публичным: GitHub → Packages → lodestone → Package settings → Change visibility.
- Или создайте секрет для pull:
  ```bash
  kubectl -n lodestone create secret docker-registry ghcr \
    --docker-server=ghcr.io --docker-username=<you> --docker-password=<PAT с read:packages>
  ```
  Затем укажите в values `imagePullSecrets: [{name: ghcr}]`.

**Вариант Б, закрытый контур.** Соберите образ сами и положите в свой реестр. Dockerfile принимает зеркала:

```bash
docker build -t harbor.corp.local/tools/lodestone:0.1.0 \
  --build-arg NODE_IMAGE=harbor.corp.local/docker-hub/library/node:22-alpine \
  --build-arg PYTHON_IMAGE=harbor.corp.local/docker-hub/library/python:3.12-slim \
  --build-arg NPM_REGISTRY=https://nexus.corp.local/repository/npm-proxy/ \
  --build-arg PIP_INDEX_URL=https://nexus.corp.local/repository/pip-proxy/simple .
docker push harbor.corp.local/tools/lodestone:0.1.0
```

## Шаг 3. Namespace

```bash
kubectl create namespace lodestone
```

## Шаг 4. База данных

Создайте пользователя и базу; пользователь должен быть владельцем базы, потому что миграции создают таблицы, типы и схему `analytics`:

```sql
CREATE ROLE lodestone LOGIN PASSWORD '<пароль>';
CREATE DATABASE lodestone OWNER lodestone ENCODING 'UTF8';
```

Строка подключения для шага 5 (драйвер psycopg 3):

```
postgresql+psycopg://lodestone:<пароль>@pg.corp.local:5432/lodestone?sslmode=require
```

Убедитесь, что поды из namespace `lodestone` достают до PostgreSQL. Если в кластере есть NetworkPolicy или файрвол, откройте доступ.

## Шаг 5. Секреты

Все секреты хранятся в одном Secret `lodestone`. В Git и в values их не кладём.

```bash
kubectl -n lodestone create secret generic lodestone \
  --from-literal=secret-key="$(openssl rand -hex 32)" \
  --from-literal=encryption-key="$(openssl rand -hex 32)" \
  --from-literal=database-url='postgresql+psycopg://lodestone:<пароль>@pg.corp.local:5432/lodestone?sslmode=require' \
  --from-literal=admin-password='<длинный пароль break-glass админа>' \
  --from-literal=ldap-bind-password='<пароль svc-lodestone>' \
  --from-literal=smtp-password='<пароль SMTP>'
# при SSO добавьте: --from-literal=oidc-client-secret='<secret из Keycloak>'
```

| Ключ | Обязателен | Что это |
|---|---|---|
| `secret-key` | да | Подпись сессий. При смене все пользователи разлогинятся |
| `database-url` | да | Строка подключения к PostgreSQL |
| `encryption-key` | желательно | Шифрует секреты в БД (пароли LDAP/OIDC/SMTP из админки, токены мессенджеров). **Потеря ключа = секреты придётся ввести заново** |
| `admin-password` | нет | Локальный админ на случай, если AD недоступен |
| `ldap-bind-password`, `oidc-client-secret`, `smtp-password` | нет | Пароли для AD, SSO и почты |
| `setup-token` | нет | Токен мастера первого запуска, если нет ни админа, ни LDAP/SSO |

Сохраните `secret-key` и `encryption-key` в хранилище секретов (Vault, Bitwarden): они понадобятся при переезде или восстановлении.

Корневой сертификат для LDAPS:

```bash
kubectl -n lodestone create secret generic corp-ca --from-file=ca.crt=./corp-root-ca.crt
```

## Шаг 6. Values

Возьмите пример [deploy/examples/values-prod.yaml](../deploy/examples/values-prod.yaml) и замените в нём:
- `image.repository` и `image.tag`;
- `ingress.host` и TLS: issuer cert-manager или `secretName` с готовым сертификатом;
- параметры AD: `url`, `bindDn`, `userBase`, `allowedGroup`, `adminGroup`;
- SMTP: `host` и `from`;
- `notifications.lang: ru`, если письма должны быть на русском.

Для SSO через Keycloak, Entra ID или ADFS поставьте `auth.oidc.enabled: true` и заполните `issuer` и `clientId`. У провайдера зарегистрируйте redirect URI:

```
https://tracker.corp.local/api/auth/oidc/sso/callback
```

## Шаг 7. Проверка чарта до установки

```bash
helm lint deploy/helm/lodestone -f values-prod.yaml
helm template lodestone deploy/helm/lodestone -n lodestone -f values-prod.yaml > /tmp/rendered.yaml
kubectl apply --dry-run=server -n lodestone -f /tmp/rendered.yaml
```

## Шаг 8. Установка

```bash
helm upgrade --install lodestone deploy/helm/lodestone -n lodestone -f values-prod.yaml --wait --timeout 10m
kubectl -n lodestone get pods
kubectl -n lodestone logs deploy/lodestone -c migrate     # при успехе пусто; ошибки миграций видны здесь
kubectl -n lodestone logs deploy/lodestone -c app | head
```

Init-контейнер `migrate` применяет миграции при каждом выкатывании. Миграции идут под advisory lock PostgreSQL, поэтому несколько подов могут стартовать одновременно.

## Шаг 9. Проверка

```bash
curl -fsS https://tracker.corp.local/healthz          # {"status":"ok"}
```

1. Откройте `https://tracker.corp.local` и войдите под учёткой AD из группы `Lodestone Users`.
2. Войдите под учёткой из `Lodestone Admins`. В меню должно быть «Администрирование».
3. Администрирование → Вход: убедитесь, что провайдер AD подтянулся из values. Кнопка «Проверить подключение» проверяет соединение и сервисную учётку.
4. Администрирование → Уведомления → «Отправить тестовое письмо».
5. Создайте проект и задачу, перетащите её по доске.

Если в values не задан ни админ, ни LDAP, ни SSO, откроется мастер первого запуска. Токен для него ищите в логе:

```bash
kubectl -n lodestone logs deploy/lodestone -c app | grep "Setup token"
```

## Шаг 10. После запуска

- **Роли.** В разделе Администрирование → Группы назначьте роли группам AD: глобально или на отдельный проект.
- **Импорт** из Jira, Plane или Confluence делается в разделе Администрирование → Импорт. Поды ходят к источнику сами, поэтому разрешите egress до `jira.corp.local` и других источников. Импорт выполняется внутри веб-пода. Если под перезапустить во время импорта, задание через 15 минут получит статус «ошибка». Его можно просто запустить снова: повторный импорт обновляет перенесённое и не создаёт копий.
- **Мессенджеры.** Вебхуки на внутренние адреса (Mattermost, Rocket.Chat в локальной сети) разрешены только при `notifications.allowPrivateWebhooks: true`.
- **Отдельный воркер уведомлений.** Задайте `notifications.worker.separate: true`, если нужно, чтобы веб-поды не отправляли почту сами.
- **Power BI.** Создайте роль только для чтения на схему `analytics`, как описано в README, раздел Analytics. После обновлений, которые меняют представления, выполните `GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO bi_ro` повторно.

## Шаг 11. Бэкапы

Все данные хранятся в PostgreSQL, у подов нет состояния. Достаточно бэкапить базу (pg_dump, pgBackRest или средства оператора) и Secret `lodestone`. Пример ежедневного дампа:

```bash
pg_dump "postgresql://lodestone:<пароль>@pg.corp.local/lodestone" -Fc -f lodestone-$(date +%F).dump
```

Восстановление: `pg_restore` в пустую базу, тот же Secret, `helm upgrade --install`.

## Шаг 12. Обновления

```bash
git pull && git tag v0.2.0 && git push origin v0.2.0     # CI соберёт образ 0.2.0
pg_dump ... -Fc -f before-0.2.0.dump                     # бэкап до миграций
helm upgrade lodestone deploy/helm/lodestone -n lodestone -f values-prod.yaml --set image.tag=0.2.0 --wait
```

`helm rollback` возвращает поды, но не схему базы. Если новая версия содержит миграции, откатывайтесь через восстановление дампа, сделанного до обновления.

## Если что-то не так

| Симптом | Где смотреть |
|---|---|
| Под в `Init:CrashLoopBackOff` | `kubectl logs <pod> -c migrate`: обычно неверный `database-url` или у пользователя нет прав владельца базы |
| `ImagePullBackOff` | Пакет в GHCR приватный, а `imagePullSecrets` не задан (шаг 2) |
| После входа сразу выкидывает на страницу входа | Сайт открыт по http: cookie ставится только по HTTPS. Нужен TLS на Ingress |
| «Wrong username or password» у всех учёток AD | Администрирование → Вход → «Проверить подключение». Частые причины: `bindDn` или пароль, CA для LDAPS, `userFilter` |
| То же сообщение только у части людей | Они не состоят в `allowedGroup` (Lodestone намеренно не говорит причину). Для вложенных групп AD нужен `nestedGroups: true` |
| SSO возвращает ошибку redirect_uri | Redirect URI у провайдера должен совпадать с шагом 6 до символа |
| Письма не уходят | Администрирование → Уведомления → журнал доставки, там видна ошибка SMTP |
| Импорт падает с «access denied» | Неверный токен. Для Cloud логин — это e-mail, для Server — логин или пусто для персонального токена |
| Импорт падает с ошибкой соединения | Нет egress из namespace до Jira или Confluence |
