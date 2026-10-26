# Подпись кода через SignPath Foundation

SignPath Foundation бесплатно подписывает сборки открытых проектов. Сертификат
выдан на SignPath Foundation: в свойствах файла издателем будет указан
SignPath Foundation. Права на программу остаются у автора. Публичная часть —
[политика подписи кода](https://modbusreader.ru/code-signing/)
(`docs/code-signing.md`), её SignPath требует на сайте проекта.

Как устроена сборка: `.github/workflows/build.yml`, задание `windows`. Оно
отправляет в SignPath два запроса на подпись:

| Запрос | Конфигурация | Что подписывается |
|---|---|---|
| 1 | [`programs.xml`](programs.xml), slug `programs` | программа (`dist/ModbusReader/ModbusReader.exe`), запускающий файл установленной копии, портативные `ModbusReader.exe` и `ModbusReader_debug.exe` |
| 2 | [`installer.xml`](installer.xml), slug `installer` | `ModbusReader-Setup.exe`, собранный уже из подписанных файлов |

Пока в репозитории нет переменной `SIGNPATH_ORGANIZATION_ID`, задание собирает
те же файлы без подписи.

## 1. До заявки

1. Слейте в `main` изменения с этой папкой. Сайт опубликуется сам, и
   страница https://modbusreader.ru/code-signing/ должна открываться.
2. Проверьте сборку на GitHub Actions: **Actions → build → Run workflow**
   (ветка `main`). Через 15–20 минут в запуске появится артефакт `windows` с
   `ModbusReader-Setup.exe`, портативными exe и снимком экрана. Установите
   этот `ModbusReader-Setup.exe` у себя и убедитесь, что всё работает так же,
   как с локальной сборкой. Отличие от локальной сборки одно: на GitHub нет
   UPX, поэтому exe не сжаты им (файлы чуть больше, зато антивирусы меньше
   придираются).
3. Выпускайте версии из этой сборки (см. раздел 5) — ещё до подписи.
   SignPath подписывает только проекты, которые уже выпускаются в том виде,
   в каком будут подписываться.
4. Включите двухфакторную аутентификацию на GitHub: **Settings → Password
   and authentication → Two-factor authentication**. SignPath требует её у
   всех, кто вносит код и утверждает подпись.

## 2. Заявка

На https://signpath.org откройте **Apply** (условия — https://signpath.org/terms)
и заполните форму. Данные для неё:

| Поле | Значение |
|---|---|
| Project name | ModbusReader |
| Repository | https://github.com/Mercurrial/ModbusReader |
| Homepage | https://modbusreader.ru/ |
| Download page | https://github.com/Mercurrial/ModbusReader/releases/latest |
| Code signing policy | https://modbusreader.ru/code-signing/ |
| License | GPL-3.0-or-later |
| Build system | GitHub Actions (GitHub-hosted runners), `.github/workflows/build.yml` |
| What to sign | Windows PE files: an Inno Setup installer and PyInstaller executables, a small C# launcher |

Описание проекта (на английском):

> ModbusReader is a free, open-source desktop tool for commissioning and
> monitoring Modbus RTU and Modbus TCP devices: a register map with names
> and units, live trends, an HMI-style dashboard, a bus scanner, an RS-485
> sniffer, Python macros and a Modbus slave simulator. Windows, Linux and
> macOS; Russian and English UI. All components are open source (see
> THIRD_PARTY_LICENSES.md). Windows releases are built by GitHub Actions
> from the tagged source; we would like to sign the installer and the
> executables so that users stop seeing SmartScreen's "unknown publisher"
> warning.

Если спросят про состав сборки: все библиотеки открытые
(`THIRD_PARTY_LICENSES.md`); загрузчик PyInstaller — GPL-2.0 с исключением
для загрузчика; Inno Setup — открытый исходный код
(https://github.com/jrsoftware/issrc) под собственной разрешительной лицензией.

Ответ придёт на почту — обычно через несколько дней, иногда через несколько недель.

## 3. Настройка в SignPath

После одобрения придёт приглашение на https://app.signpath.io. Войдите и
включите двухфакторную аутентификацию в своём профиле.

Названия пунктов меню могут немного отличаться — ориентируйтесь на смысл.
Обычно SignPath Foundation сама создаёт проект, политики подписи
`test-signing` и `release-signing` и подключает GitHub как доверенную систему
сборки. Проверьте и дополните:

1. **Projects → ModbusReader.** Запомните **slug** проекта. Если он не
   `ModbusReader`, его нужно будет указать в GitHub (раздел 4). В настройках
   проекта должен стоять репозиторий
   `https://github.com/Mercurrial/ModbusReader`, в **Trusted Build Systems**
   — GitHub.com.
2. **Artifact Configurations → Add**, две штуки:
   - slug `programs`, содержимое — файл [`programs.xml`](programs.xml)
     целиком;
   - slug `installer`, содержимое — файл [`installer.xml`](installer.xml).
3. **Signing Policies.** В `release-signing` утверждающим (Approver) должны
   быть вы. Тот, кто отправляет запросы (Submitter), — пользователь из
   следующего шага.
4. **Users → Add CI user** (например, `github-actions`), затем **Generate API
   token** — скопируйте токен сразу, второй раз его не покажут. Добавьте
   этого пользователя в **Submitters** обеих политик (`test-signing` и
   `release-signing`).
5. **ID организации** — в **Settings** организации (Organization ID, вида
   `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`) или в адресе страницы
   `app.signpath.io/Web/<ID>/…`.

## 4. Настройка в GitHub

Репозиторий → **Settings → Secrets and variables → Actions**:

- вкладка **Secrets → New repository secret**:
  `SIGNPATH_API_TOKEN` — токен из шага 3.4;
- вкладка **Variables → New repository variable**:
  `SIGNPATH_ORGANIZATION_ID` — ID организации из шага 3.5. С этой переменной
  подпись включается;
- только если slug проекта не `ModbusReader`: переменная
  `SIGNPATH_PROJECT_SLUG`.

### Пробный запуск

1. Добавьте переменную `SIGNPATH_SIGNING_POLICY_SLUG` = `test-signing`.
2. **Actions → build → Run workflow** (ветка `main`).
3. Задание дойдёт до шага «Sign the programs» и будет ждать (до часа). На
   app.signpath.io в **Signing Requests** появится запрос: откройте его и
   нажмите **Approve**, если политика требует утверждения. Затем то же для
   «Sign the installer».
4. Шаг «Signatures» покажет каждый файл с подписью. Тестовый сертификат
   Windows не доверяет — для пробы этого достаточно.
5. Удалите переменную `SIGNPATH_SIGNING_POLICY_SLUG`: без неё используется
   `release-signing`.

## 5. Выпуск версии

```bash
python tools/release.py          # номер версии, CHANGELOG
python -m pytest
git commit -am "release: ГГ.ММ.N"
git tag -a vГГ.ММ.N -m "ModbusReader ГГ.ММ.N"
git push origin main vГГ.ММ.N
```

Тег запускает **Actions → build**. Задание `windows` дважды остановится и
будет ждать утверждения на app.signpath.io: сначала программы, потом
установщик. SignPath пришлёт письмо о каждом запросе. На каждое утверждение
есть час; если не успели, перезапустите задание (**Re-run failed jobs**).

Когда все три задания (`windows`, `linux`, `macos`) зелёные, скачайте файлы и
загрузите их в выпуск. Команды печатает `tools/release.py`:

```bash
gh run download <номер запуска> -D dist/ci -n windows -n linux -n macos
gh release upload <текущий тег> --clobber dist/ci/windows/ModbusReader-Setup.exe ...
gh release edit <текущий тег> --tag vГГ.ММ.N --title "ModbusReader ГГ.ММ.N" --notes-file <заметки>
```

Перед загрузкой проверьте подпись: **Свойства → Цифровые подписи → SignPath
Foundation** у `ModbusReader-Setup.exe`.

## 6. После первого подписанного выпуска

- Поправьте тексты про SmartScreen: теперь программа подписана, а
  предупреждение может появиться только у совсем новой версии. Тексты лежат
  в `README.md` («Windows может предупредить»), `docs/install.md` и
  `docs/install.en.md` (раздел `#smartscreen`), `docs/troubleshooting.md` и
  `docs/troubleshooting.en.md`, а также в строке «Known limitations» в
  `ARCHITECTURE.md`.
- По желанию отправляйте `ModbusReader-Setup.exe` каждой новой версии в
  Microsoft: https://www.microsoft.com/wdsi/filesubmission → Software
  developer → Microsoft Defender SmartScreen. Так предупреждение для новой
  версии пропадёт быстрее.

## Чего не делать

- Не подписывайте этим сертификатом чужие файлы и не собирайте файлы выпуска
  на своём компьютере: SignPath подписывает только то, что собрал GitHub
  Actions из этого репозитория.
- Не добавляйте в программу закрытые компоненты, рекламу или незаявленную
  передачу данных. Это нарушит условия SignPath Foundation, и она может
  отозвать подпись. Если программа начнёт передавать что-то по сети сама,
  сначала допишите это в раздел «Конфиденциальность» политики.
