# План разработки wb-mqtt-zigbee


## Этапы разработки

| Этап | Название | Оценка | Статус |
|---|---|---|---|
| 1 | Основа + сервис + упаковка | 0.5-1  дня | ✅ Выполнен |
| 2 | Устройство моста | 1–2 дня | ✅ Выполнен |
| 3 | Обнаружение устройств (readonly) | 2–3 дня | ✅ Выполнен |
| 4 | Управление устройствами | 1–2 дня | ✅ Выполнен |
| 5 | Жизненный цикл устройств | 0.5–1 день | ✅ Выполнен |
| 6 | OTA | 1–2 дня | |
| 7 | Группы | 1–2 дня | |
| | **Итого** | **7–13 дней** | |

---

### Этап 1 — Основа + сервис + упаковка (0.5 дня) ✅

**Что сделали:** структура проекта, `config_loader.py` (загрузка JSON-конфига), `main.py` (MQTT-клиент, обработка сигналов, коды выхода), `debian/wb-mqtt-zigbee.service`, `configs/wb-mqtt-zigbee.conf`, `setup.py`, `bin/wb-mqtt-zigbee`, тесты на `config_loader.py`.

**Результат:** deb-пакет собирается, устанавливается на железо, сервис стартует через `systemctl` и подключается к MQTT-брокеру.

**Проверка:**
- `apt install ./wb-mqtt-zigbee.deb` — пакет устанавливается без ошибок
- `systemctl status wb-mqtt-zigbee` — сервис в состоянии `active (running)`
- Перезапуск MQTT-брокера → сервис переподключается автоматически, в логах нет необработанных исключений

---

### Этап 2 — Устройство моста (1–2 дня) ✅

**Что сделали:** подписка на `bridge/state`, `bridge/info`, `bridge/logging`, `bridge/devices`, `bridge/event`, `bridge/response/device/remove`; виртуальное WB-устройство `zigbee2mqtt` с 12 контролами; фильтрация логов по уровню; JSON `/meta` с en/ru переводами.

**Контролы устройства моста:**

| Контрол | Тип | ReadOnly | Описание |
|---|---|---|---|
| State | text | R | Состояние моста (online/offline/error) |
| Version | text | R | Версия zigbee2mqtt |
| Permit join | switch | W | Разрешить подключение устройств (254 сек) |
| Device count | value | R | Количество устройств (без координатора) |
| Last joined | text | R | Последнее подключенное устройство |
| Last left | text | R | Последнее вышедшее из сети устройство |
| Last removed | text | R | Последнее удалённое устройство |
| Update devices | pushbutton | W | Запросить обновление списка устройств |
| Last seen | text | R | Последняя активность (время последнего сообщения от z2m) |
| Messages received | value | R | Количество полученных сообщений от z2m |
| Log level | text | R | Минимальный уровень логов (из конфига) |
| Log | text | R | Последнее лог-сообщение (фильтруется по уровню) |

**Результат:** в WB появляется устройство `Zigbee2MQTT`, все контролы обновляются в реальном времени, permit_join работает, логи фильтруются по настроенному уровню.

**Проверка:**
- WB UI показывает устройство `Zigbee2MQTT` с актуальными State и Version
- Переключение Permit join → в z2m UI режим сопряжения включается/выключается
- Нажатие Update devices → в логах z2m видно запрос на обновление списка устройств
- Подключение/отключение/удаление устройства → соответствующий контрол обновляется

#### Исследование MQTT API z2m (bridge topics)

**`zigbee2mqtt/bridge/info`** — публикуется при старте и при изменении состояния:

```json
{
  "version": "1.13.0",
  "commit": "772f6c0",
  "coordinator": { "type": "zStack30x", "ieee_address": "0x12345678", "meta": {} },
  "network": { "channel": 15, "pan_id": 5674, "extended_pan_id": [0, 11, 22] },
  "permit_join": true,
  "permit_join_end": 1733666394,
  "log_level": "debug",
  "restart_required": false
}
```

Версия z2m берётся из поля `version` — отдельный топик не нужен.

**`zigbee2mqtt/bridge/state`** — строка `"online"` / `"offline"` / `"error"`.

**`zigbee2mqtt/bridge/logging`** — лог-сообщения от z2m в реальном времени.

#### permit_join

Топик одинаковый для v1.x и v2.x: `zigbee2mqtt/bridge/request/permit_join`.

Единственное отличие v2.x — убрана возможность включить навсегда, максимум 254 секунды. Разницы в коде нет — всегда шлём:

```json
{ "time": 254 }   // включить
{ "time": 0 }     // выключить
```

#### update_devices

Re-subscribe на `zigbee2mqtt/bridge/devices` (unsubscribe + subscribe) — брокер повторно доставит retained-сообщение. В z2m 2.x топик `bridge/request/devices/get` удалён.

#### Модули

| Модуль | Что реализовано |
|---|---|
| `z2m/model.py` | `BridgeInfo`, `BridgeState`, `Z2MEventType`, `DeviceEventType`, `DeviceEvent`, `BridgeLogLevel` |
| `z2m/client.py` | `Z2MClient`: подписка на 6 топиков (state, info, logging, devices, event, response/device/remove); парсинг → типизированные коллбэки |
| `wb_converter/controls.py` | `BridgeControl` (ID контролов), `ControlMeta` (type, readonly, order, title), `BRIDGE_CONTROLS` (10 контролов с en/ru переводами) |
| `wb_converter/publisher.py` | `WbPublisher`: публикация WB-устройства с JSON `/meta`, начальных значений контролов, подписка на команды (permit_join, update_devices) |
| `bridge.py` | `Bridge`: оркестратор — z2m-события → WB-контролы, фильтрация логов по `bridge_log_min_level` |

---

### Этап 3 — Обнаружение устройств (readonly) (2–3 дня) ✅

**Что сделали:**

- Парсинг `bridge/devices`: `Z2MDevice.from_dict()` с `ExposeFeature` (рекурсивный парсинг вложенных features)
- Маппинг `exposes` → WB-контролы: `expose_mapper.py` с 12 numeric-маппингами, binary, enum, text, rgb (color picker), range (слайдер для writable numerics с min/max)
- Динамическое создание WB-устройств с JSON `/meta` и en/ru переводами
- Запрос актуального состояния через `{device}/get` при регистрации
- Подписка на `zigbee2mqtt/{friendly_name}` для обновления состояния в реальном времени
- Конвертация значений z2m → WB: `ControlMeta.format_value()` (bool, binary value_on/value_off, HS→RGB для цветных ламп, dict→JSON)
- Обработка `last_seen` в трёх форматах: epoch ms, epoch s, ISO строка (конвертация в локальное время)
- Идентификация: `ieee_address` для WB `device_id` (уникальный, стабильный), `friendly_name` для отображения и подписок z2m
- Кеширование: `RegisteredDevice` (z2m device + controls + device_id) — избегаем пересчёта на каждое сообщение
- Пропуск устройств без `exposes` (не прошли interview) и без маппируемых контролов
- Типовые константы: `ExposeType`, `ExposeProperty` (model.py), `WbControlType` (controls.py) — вместо строковых литералов
- Валидация `bridge_log_min_level` в конфиге с предупреждением и fallback

**Сделано «по пути» (из этапа 5 — жизненный цикл):**

- Удаление устройств: обработка `device_removed` и `device_leave` — отписка от z2m-топика, очистка retain-сообщений WB, удаление из `_known_devices`
- Переименование устройств: обработка через `bridge/event` (`device_renamed`) и через `bridge/devices` (обнаружение по `ieee_address`) — переподписка на новый z2m-топик, обновление `_known_devices`, перепубликация title в WB (device_id на основе ieee_address не меняется)

**Модули:**

| Модуль | Что реализовано |
|---|---|
| `z2m/model.py` | + `ExposeFeature`, `ExposeAccess`, `ExposeType`, `ExposeProperty`, `Z2MDevice`, `Z2MEventType.DEVICE_RENAMED`, `DeviceEventType.RENAMED`, поле `old_name` в `DeviceEvent` |
| `z2m/client.py` | + `subscribe_device`, `unsubscribe_device`, `request_device_state`, обработка `device_renamed` |
| `wb_converter/expose_mapper.py` | Новый модуль: `map_exposes_to_controls()`, `NUMERIC_TYPE_MAP` (12 типов), `NESTED_TYPES`, `_resolve_wb_type`, `_map_color_feature` (composite color → rgb), auto-range для writable numerics с min/max |
| `wb_converter/controls.py` | + `WbControlType` (16 констант, вкл. RANGE, RGB), `ControlMeta.format_value()` (вкл. HS→RGB через `colorsys`), поля `value_on`/`value_off` |
| `wb_converter/publisher.py` | + `publish_device()`, `publish_device_control()`, `remove_device()` |
| `registered_device.py` | Новый модуль: `RegisteredDevice` dataclass |
| `bridge.py` | + `_register_device`, `_on_device_state`, `_on_device_renamed`, `_find_old_name`, `_format_last_seen`, `_sanitize_device_id` |
| `config_loader.py` | + валидация `bridge_log_min_level` |

**Результат:** все Zigbee-устройства отображаются в WB с правильными типами контролов и актуальными значениями. Удаление и переименование устройств в z2m отражается в WB без перезапуска сервиса.

**Проверка (пройдена на 5 устройствах: 2 реле, датчик температуры, 2 датчика):**
- После `systemctl restart wb-mqtt-zigbee` все устройства появляются в WB в течение нескольких секунд
- Значения контролов совпадают с тем, что показывает z2m UI
- Датчик температуры меняет значение → контрол в WB обновляется в реальном времени
- Реле показывает корректное состояние (ON/OFF → 1/0 через value_on/value_off)
- Устройства с вложенными `exposes` (composite/specific features) корректно разворачиваются
- Удаление устройства в z2m → WB-устройство исчезает, retain-топики очищены
- Устройство без завершённого interview пропускается, после interview регистрируется при следующем обновлении

---

### Этап 4 — Управление устройствами (1–2 дня) ✅

**Что сделали:** подписка на `/on`-топики WB при регистрации устройства, маппинг команд через `parse_wb_value()` → публикация в `zigbee2mqtt/{device}/set`. Отписка от команд при удалении устройства. Добавлены сервисные контролы к каждому устройству:

- `device_type` (text, readonly) — тип устройства в z2m сети (Router → Маршрутизатор, EndDevice → Оконечное устройство, Coordinator → Координатор)
- `last_seen` (text, readonly) — время последней активности устройства (конвертация из epoch ms/s/ISO → локальное время)

**Результат:** writable-контролы в WB отправляют команды на устройства. Каждое устройство показывает свой тип и время последней активности.

**Проверка:**
- Переключение реле из WB → физическое устройство реагирует
- Изменение яркости/цветовой температуры лампы из WB → устройство реагирует
- Команда отражается обратно в WB (z2m публикует новое состояние после выполнения)

---

### Этап 5 — Жизненный цикл устройств (0.5–1 день) ✅

**Уже сделано (в рамках этапа 3):**
- ✅ Удаление устройств (`device_removed`, `device_leave`) — отписка, очистка retain, удаление из `_known_devices`
- ✅ Переименование устройств (`device_renamed`) — переподписка на новый топик, обновление title в WB

**Добавлено:**
- ✅ Очистка stale-устройств — при каждом `bridge/devices` удаляются устройства из `_known_devices`, которых нет в актуальном списке z2m
- ✅ Очистка ghost-устройств при старте — wildcard-сканирование retained `/devices/+/meta` по маркеру `"driver": "wb-zigbee2mqtt"`, сравнение с первым `bridge/devices`, удаление отсутствующих
- ✅ Маркер `driver` в device meta — все WB-устройства публикуются с `"driver": "wb-zigbee2mqtt"` для идентификации
- ✅ Очистка legacy meta sub-topics при удалении (`meta/type`, `meta/order`, `meta/readonly`, `meta/name`, `meta/driver`)
- ✅ `postinst` — автоматическое удаление v1 wb-rules скрипта (`wb-zigbee2mqtt.js` / `.disabled`) при установке пакета

**Дополнительно реализовано:**
- ✅ Обновление `exposes` при изменении — контролы перерегистрируются автоматически
- ✅ Валидация `friendly_name` — MQTT wildcard символы (+, #) отклоняются
- ✅ Устойчивость к ошибкам — битое устройство в списке не блокирует обработку остальных

**Проверка (пройдена):**
- Удалить устройство в z2m UI → устройство исчезает из WB ✅
- Переименовать устройство в z2m UI → в WB появляется новое имя, device_id не меняется ✅
- Удалить устройства, перезапустить сервис → ghost-устройства очищаются при старте ✅
- Устройства других драйверов не затрагиваются ghost-сканированием ✅
- Установка пакета на систему с v1 скриптом → скрипт удаляется, wb-rules перезапускается ✅

**Проверка (пройдена после реализации Stage 4):**
- После переименования управление устройством из WB продолжает работать ✅

---

### Этап 6 — OTA (1–2 дня)

**Что делаем:** OTA-контролы с динамической видимостью (`ota_installed_version`, `ota_check`, `ota_check_state`, `ota_latest_version`, `ota_update`, `ota_state`, `ota_progress`).

**Результат:** пользователь видит версию прошивки, может проверить наличие обновления и запустить его с отображением прогресса.

**Проверка:**
- На устройстве с поддержкой OTA появляются контролы `ota_installed_version` и `ota_check`
- Нажатие `ota_check` → появляется `ota_check_state` со статусом проверки, исчезает по завершении
- Если обновление найдено → появляются `ota_latest_version` и `ota_update`
- Нажатие `ota_update` → появляется `ota_progress` с обновляющимся значением

---

### Этап 7 — Группы (1–2 дня)

**Что делаем:** подписка на `bridge/groups`, создание WB-устройств для групп с фиксированным набором контролов (`state`, `brightness`, `color_temp`) и контролом `members`.

**Результат:** группы z2m отображаются в WB как отдельные устройства, поддерживают команды.

**Проверка:**
- Создать группу в z2m → устройство группы появляется в WB
- Отправить команду группе из WB → все устройства-члены группы реагируют
- Контрол `members` содержит актуальный список участников



## Структура проекта

```
wb-mqtt-zigbee/
├── wb/
│   └── zigbee2mqtt/             — Python-пакет (namespace wb)
│       ├── __init__.py
│       ├── __main__.py
│       ├── main.py              — setup_logging(), main() (точка входа)
│       ├── app.py               — WbZigbee2Mqtt (MQTT-клиент, сигналы, коды выхода)
│       ├── config_loader.py     — ConfigLoader (dataclass), load_config()
│       ├── bridge.py            — оркестратор: z2m-события → WB-контролы
│       ├── registered_device.py — RegisteredDevice: кеш устройства (z2m + controls + device_id)
│       ├── mqtt_client.py       — зарезервировано
│       ├── z2m/
│       │   ├── client.py        — Z2MClient: подписка на z2m-топики + устройства, парсинг → коллбэки
│       │   ├── model.py         — Z2MDevice, ExposeFeature, ExposeType, ExposeProperty, BridgeInfo, ...
│       │   └── ota.py           — зарезервировано (TODO: этап 6)
│       └── wb_converter/
│           ├── publisher.py     — WbPublisher: публикация/удаление WB-устройств и JSON /meta
│           ├── controls.py      — WbControlType, BridgeControl, ControlMeta (с format_value)
│           ├── expose_mapper.py — маппинг z2m exposes → WB ControlMeta
│           (subscriber.py удалён — подписка на команды в publisher.py)
├── bin/
│   └── wb-mqtt-zigbee           — точка входа → /usr/bin/wb-mqtt-zigbee
├── configs/
│   └── wb-mqtt-zigbee.conf      — дефолтный конфиг (JSON, → /usr/lib/wb-mqtt-zigbee/configs/)
├── docs/
│   ├── arc42.md                 — архитектура в формате arc42
│   ├── development-plan.md      — план разработки, структура, модули (этот файл)
│   └── v1-analysis.md           — анализ предыдущей версии (JS/wb-rules)
├── debian/
│   ├── control
│   ├── changelog                — источник версии пакета
│   ├── rules
│   ├── copyright
│   ├── wb-mqtt-zigbee.postinst  — удаление v1 wb-rules скрипта при установке
│   ├── wb-mqtt-zigbee.service   — systemd unit
│   └── wb-mqtt-zigbee.install   — раскладка не-Python файлов
├── setup.py
└── pyproject.toml               — конфигурация black, isort, pylint (не коммитится)
```

## Поток данных

```
             ┌─────────────────────┐
             │   Zigbee-устройства │
             │  (датчики, реле,    │
             │   лампы, ...)       │
             └──────────┬──────────┘
                        │ Zigbee (двунаправленно)
             ┌──────────▼──────────┐
             │     zigbee2mqtt     │
             │  (координатор Zigbee│
             │   + MQTT издатель)  │
             └──────────┬──────────┘
                        │ MQTT zigbee2mqtt/* (двунаправленно)
             ┌──────────▼──────────┐
             │  Mosquitto брокер   │
             └──────────┬──────────┘
                        │ MQTT /devices/* (двунаправленно)
         ┌──────────────┼──────────────────┐
         │              │                  │
┌────────▼────────┐  ┌──▼─────────────┐  ┌▼─────────────┐
│ wb-mqtt-zigbee  │  │ wb-mqtt-serial │  │ Wiren Board  │
│   -v2 (это)     │  │ (другие        │  │   Web UI     │
│  R: zigbee2mqtt/│  │  устройства WB)│  │  (только     │
│  W: /devices/   │  └────────────────┘  │   чтение)    │
└─────────────────┘                      └──────────────┘
```

## Модули

| Модуль | Назначение | Статус |
|---|---|---|
| `main.py` | Точка входа: `setup_logging()`, парсинг CLI-аргументов, загрузка конфига | ✅ |
| `app.py` | `WbZigbee2Mqtt`: MQTT-клиент, обработка сигналов (SIGINT/SIGTERM/SIGHUP), жизненный цикл, коды выхода | ✅ |
| `config_loader.py` | Загрузка JSON-конфига, `dataclass ConfigLoader`, валидация `bridge_log_min_level` | ✅ |
| `bridge.py` | Оркестратор: z2m-события → WB-контролы, регистрация/удаление/переименование устройств, фильтрация логов | ✅ |
| `registered_device.py` | `RegisteredDevice`: кеш z2m-устройства с WB controls и device_id | ✅ |
| `z2m/client.py` | `Z2MClient`: подписка на 6 z2m-топиков + устройства, парсинг → типизированные коллбэки | ✅ |
| `z2m/model.py` | `BridgeInfo`, `BridgeState`, `DeviceEvent`, `BridgeLogLevel`, `Z2MDevice`, `ExposeFeature`, `ExposeType`, `ExposeProperty`, `ExposeAccess` | ✅ |
| `mqtt_client.py` | Зарезервировано для расширения MQTT-клиента | зарезервировано |
| `z2m/ota.py` | OTA: запрос проверки и запуск обновления | зарезервировано |
| `wb_converter/controls.py` | `WbControlType` (16 типов, вкл. RANGE, RGB), `BridgeControl`, `ControlMeta` (с `format_value`, `parse_wb_value` и HS↔RGB), `BRIDGE_CONTROLS` (12 контролов с en/ru) | ✅ |
| `wb_converter/expose_mapper.py` | Маппинг z2m exposes → WB `ControlMeta` (12 numeric типов, binary, enum, text, rgb для color) | ✅ |
| `wb_converter/publisher.py` | `WbPublisher`: публикация/удаление WB-устройств, JSON `/meta` с driver-маркером, подписка на команды, retained-сканирование ghost-устройств | ✅ |
| ~~`wb_converter/subscriber.py`~~ | Удалён — подписка на команды реализована в `publisher.py` | — |

## Конфигурация

Файл: `/usr/lib/wb-mqtt-zigbee/configs/wb-mqtt-zigbee.conf` (JSON)

```json
{
    "broker_url": "unix:///var/run/mosquitto/mosquitto.sock",
    "zigbee2mqtt_base_topic": "zigbee2mqtt",
    "bridge_log_min_level": "warning"
}
```

| Параметр | Обязателен | По умолчанию | Описание |
|---|---|---|---|
| `broker_url` | да | — | URL MQTT-брокера |
| `zigbee2mqtt_base_topic` | да | — | Базовый топик zigbee2mqtt |
| `device_id` | нет | `"zigbee2mqtt"` | ID WB-устройства моста |
| `device_name` | нет | `"Zigbee2MQTT"` | Отображаемое имя WB-устройства |
| `bridge_log_min_level` | нет | `"warning"` | Минимальный уровень логов моста (debug/info/warning/error) |

Путь по умолчанию задан в `config_loader.CONFIG_FILEPATH`, переопределяется флагом `-c`/`--config`.

## Построение контролов из exposes

В v1 типы контролов захардкожены (12 атрибутов, все readonly). В v2 используем схему `exposes`, которую zigbee2mqtt публикует для каждого устройства. Там указано:
- имя атрибута (`temperature`, `state`, `brightness`, …)
- тип (`numeric`, `binary`, `enum`, `text`)
- `access`: readonly / readwrite / writeonly
- `value_min`, `value_max`, `unit` для numeric

Контролы WB строятся динамически из `exposes` — управление устройствами появляется автоматически без захардкоженных маппингов.

Отображаемое имя контрола (title) генерируется из имени property: `noise_detect_level` → `"Noise detect level"` (`property.replace("_", " ").capitalize()`).

### Цветные лампы (RGB)

Цветные лампы в z2m имеют composite expose `color` с вложенными `x`/`y` (CIE XY) или `hue`/`saturation` (HS). В state z2m всегда отдаёт оба представления одновременно:

```json
{"color": {"x": 0.4066, "y": 0.1643, "hue": 308, "saturation": 100}, "color_mode": "xy"}
```

Вместо разворачивания composite в отдельные контролы `x`, `y`, `hue`, `saturation` (что бесполезно для пользователя), composite `color` маппится в один WB-контрол типа `rgb`. Конвертация через HS→RGB (`colorsys.hsv_to_rgb`), brightness вынесен в отдельный контрол (V=1.0). Результат — формат WB `"R;G;B"`, homeui отображает color picker.

В v1 цвет отображался как JSON-строка `{"x":0.3,"y":0.4}` — бесполезно для пользователя.

## Синхронизация состояния при старте

При старте сервиса список устройств известен из `bridge/devices`, но текущее состояние каждого устройства неизвестно — оно придёт только при следующем изменении на устройстве. Чтобы сразу отобразить актуальные значения, при инициализации каждого устройства делается запрос через MQTT:

Публикация в `zigbee2mqtt/{device_name}/get` с payload `{}` → z2m опрашивает физическое устройство → ответ приходит в обычный топик `zigbee2mqtt/{device_name}`.

## OTA

zigbee2mqtt публикует поле `update` в состоянии каждого устройства:

```json
{
  "update": {
    "state": "idle | available | updating",
    "installed_version": 65571,
    "latest_version": 65572,
    "progress": 57.3
  }
}
```

Если поле `update` отсутствует — устройство не поддерживает OTA, контролы не создаются.

OTA-контролы показываются динамически в зависимости от состояния:

| Состояние | Показываем контролы |
|---|---|
| `idle` | `ota_installed_version`, `ota_check` |
| `checking` | `ota_installed_version`, `ota_check`, `ota_check_state` |
| `available` (installed ≠ latest) | `ota_installed_version`, `ota_latest_version`, `ota_check`, `ota_update` |
| `updating` | `ota_installed_version`, `ota_latest_version`, `ota_state`, `ota_progress` |

Описание контролов:

| Контрол | Тип | Описание |
|---|---|---|
| `ota_installed_version` | text, readonly | Установленная версия прошивки |
| `ota_latest_version` | text, readonly | Доступная новая версия |
| `ota_state` | text, readonly | `updating` — отображается только во время обновления |
| `ota_progress` | value, readonly | Прогресс 0–100% |
| `ota_check` | pushbutton | Проверить наличие обновления |
| `ota_check_state` | text, readonly | `"Проверяю..."` — появляется пока идёт проверка, исчезает по завершении |
| `ota_update` | pushbutton | Запустить обновление |

Команды:
- `ota_check` → публикует в `zigbee2mqtt/bridge/request/device/ota_update/check` payload `{"id": "<ieee_address>"}`
- `ota_update` → публикует в `zigbee2mqtt/bridge/request/device/ota_update/update` payload `{"id": "<ieee_address>"}`. Показывается только когда `installed_version != latest_version`.

## Удаление и переименование устройств

zigbee2mqtt публикует события в `zigbee2mqtt/bridge/event`:

```json
{ "type": "device_removed", "data": { "friendly_name": "...", "ieee_address": "..." } }
{ "type": "device_renamed", "data": { "from": "...", "to": "..." } }
```

**Удаление:** при `device_removed` — снять подписку с топика устройства, опубликовать пустые retain-сообщения (`""`) на все топики WB-устройства (стандартный способ удалить устройство по WB MQTT Conventions).

**Переименование:** при `device_renamed` — перепубликовать title WB-устройства с новым именем, перенести подписку на новый топик z2m. Устройство не удаляется и не пересоздаётся, т.к. `device_id` основан на `ieee_address` и не меняется.

## Группы

В z2m группы публикуются в `zigbee2mqtt/bridge/groups`:

```json
[{ "id": 1, "friendly_name": "living_room", "members": [...], "scenes": [] }]
```

Каждая группа ведёт себя как устройство: имеет топик `zigbee2mqtt/{group_name}` и поддерживает команды.

Группы обрабатываются тем же кодом, что и устройства, с отличиями:
- В `model.py` флаг `is_group: bool`
- `exposes` у групп не публикуются — используется фиксированный набор: `state`, `brightness`, `color_temp`
- В WB-устройстве группы дополнительный readonly контрол `members` со списком участников

---

## Проработанные альтернативы

### Альтернатива: HA MQTT Discovery вместо exposes

**Идея:** включить HA-интеграцию в zigbee2mqtt. Тогда z2m сам публикует метаданные каждого атрибута в стандартизированном формате HA MQTT Discovery, который легче парсить, чем `exposes`.

При включённой HA-интеграции z2m публикует в `homeassistant/{component}/{device_id}/{attribute}/config`:

```json
{
  "state_topic": "zigbee2mqtt/my_sensor",
  "value_template": "{{ value_json.temperature }}",
  "unit_of_measurement": "°C",
  "device_class": "temperature",
  "device": { "identifiers": ["zigbee2mqtt_0x1234"], "name": "my_sensor" }
}
```

Для writable-атрибутов явно присутствует `command_topic` — не нужно разбирать поле `access`.

**Сравнение с exposes:**

| | HA Discovery | exposes |
|---|---|---|
| Readable/writable | явно: `command_topic` есть → writable | нужно разбирать поле `access` |
| Типы | `device_class` + `unit_of_measurement` | вложенная структура (`numeric`/`binary`/`enum`) |
| Сложность парсинга | умеренная | высокая (composite/specific features) |
| Удаление устройства | пустой payload в discovery-топик | `bridge/event` → `device_removed` |
| Зависимость | нужно включить HA integration в конфиге z2m | ничего дополнительно |
| Официальность | побочный механизм (для HA) | основной API для интеграций |

**Почему отклонили:**

1. **Хрупкая зависимость** — если пользователь выключит HA integration в z2m, сервис перестанет работать.
2. **Формат не для нас** — HA Discovery заточен под HA-сущности (`sensor`, `switch`, `light`, `climate`). Маппинг HA-компонентов → WB-контролы требует такой же таблицы соответствий, как и exposes → WB, но для этого пока нет готового маппинга.
3. **Группировка** — HA публикует одну запись на каждый атрибут, атрибуты нужно собирать в устройство по `device.identifiers`.

**Решение:** оставить `exposes` как основной источник метаданных. HA Discovery можно рассмотреть позже, когда появится готовый маппинг HA device_class → WB control type.

---

## Открытые вопросы

### ❓ Миграция с v1 на v2

**Проблема:** пользователи v1 имеют правила wb-rules, которые ссылаются на WB-устройства и контролы по именам. В v2 имена могут измениться, что сломает все существующие правила.

**Что меняется:**
- Имена WB-устройств — в v2 появляется префикс `zigbee_` (например, `living_room_sensor` → `zigbee_living_room_sensor`)
- Имена контролов — в v1 брались напрямую из JSON, в v2 строятся из `exposes` и могут отличаться
- Имя устройства моста — в v1 это `zigbee2mqtt`, в v2 нужно решить

**Варианты решения:**

1. **Без миграции** — документируем breaking change, пользователь обновляет правила вручную. Просто для нас, болезненно для пользователей.

2. **Настраиваемый префикс** — добавить в конфиг параметр `device_prefix` (по умолчанию пустой) — имена WB-устройств останутся как в v1. Частично решает проблему, но не гарантирует полное совпадение имён контролов.

3. **Скрипт миграции** — при установке пакета скрипт находит все правила wb-rules, ссылающиеся на старые имена устройств и контролов, и обновляет их автоматически.

**Решение не принято.**

---
