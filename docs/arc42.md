# Архитектура wb-zigbee2mqtt-v2 (arc42)

---

## 1. Введение и цели

### Назначение системы

`wb-zigbee2mqtt-v2` — сервис-мост между [zigbee2mqtt](https://www.zigbee2mqtt.io/) и [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions). Создаёт виртуальные устройства WB на основе данных от zigbee2mqtt, транслирует состояния Zigbee-устройств в контролы WB, а команды пользователя из WB — обратно в zigbee2mqtt.

### Цели

| Приоритет | Цель |
|---|---|
| 1 | Отображать все Zigbee-устройства как нативные WB-устройства |
| 2 | Поддерживать управление устройствами (не только чтение, как в v1) |
| 3 | Поддерживать OTA-обновление прошивок устройств |
| 4 | Корректно реагировать на удаление и переименование устройств в zigbee2mqtt |
| 5 | Поддерживать группы zigbee2mqtt |

### Стейкхолдеры

| Роль | Интерес |
|---|---|
| Пользователь Wiren Board | Видит Zigbee-устройства в WB UI, управляет ими, пишет правила wb-rules |
| Разработчик | Сопровождаемый, тестируемый Python-код вместо JS/wb-rules |
| Команда Wiren Board | Возможность распространять как deb-пакет, поддерживать как systemd-сервис |

---

## 2. Ограничения

### Технические

- Python 3.9
- `python3-wb-common (>= 2.1.0)` — единственная runtime-зависимость (включает paho-mqtt)
- Установка и запуск как systemd-сервис на устройствах Wiren Board
- Распространение как deb-пакет
- Совместимость с zigbee2mqtt v1.x и v2.x

### Организационные

- Конфигурация через JSON-файл `/usr/lib/wb-zigbee2mqtt/configs/wb-zigbee2mqtt.conf`
- Сборка через Jenkins (`buildDebArchAll`)

---

## 3. Контекст системы

### Внешние системы

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
│ wb-zigbee2mqtt  │  │ wb-mqtt-serial │  │ Wiren Board  │
│   -v2 (это)     │  │ (другие        │  │   Web UI     │
│  R: zigbee2mqtt/│  │  устройства WB)│  │  (только     │
│  W: /devices/   │  └────────────────┘  │   чтение)    │
└─────────────────┘                      └──────────────┘
```

### MQTT-топики: вход (от zigbee2mqtt)

| Топик | Содержимое |
|---|---|
| `zigbee2mqtt/bridge/state` | Состояние моста (`online`/`offline`) |
| `zigbee2mqtt/bridge/info` | Версия, permit_join (z2m 1.21+) |
| `zigbee2mqtt/bridge/config` | Версия, log_level (z2m 1.18.x) |
| `zigbee2mqtt/bridge/logging` | Лог-сообщения (z2m 1.21+) |
| `zigbee2mqtt/bridge/devices` | Список устройств с `exposes`-схемой |
| `zigbee2mqtt/bridge/groups` | Список групп |
| `zigbee2mqtt/bridge/event` | События: `device_removed`, `device_renamed` |
| `zigbee2mqtt/{device_name}` | Состояние устройства |
| `zigbee2mqtt/bridge/response/permit_join` | Подтверждение смены permit_join |
| `zigbee2mqtt/bridge/response/device/ota_update/check` | Результат проверки OTA |

### MQTT-топики: выход (команды в zigbee2mqtt)

| Топик | Команда |
|---|---|
| `zigbee2mqtt/bridge/devices/get` | Запросить список устройств |
| `zigbee2mqtt/bridge/request/permit_join` | Включить/выключить сопряжение |
| `zigbee2mqtt/{device_name}/set` | Отправить команду устройству |
| `zigbee2mqtt/{device_name}/get` | Запросить текущее состояние устройства |
| `zigbee2mqtt/bridge/request/device/ota_update/check` | Проверить наличие OTA |
| `zigbee2mqtt/bridge/request/device/ota_update/update` | Запустить OTA-обновление |

---

## 4. Стратегия решения

- **Динамическое построение контролов из `exposes`** вместо захардкоженных маппингов v1. Это автоматически даёт поддержку управления и новых типов устройств без изменения кода. Отображаемое имя контрола генерируется из имени property: `noise_detect_level` → `"Noise detect level"`.
- **Event-driven внутри сервиса**: `z2m/client.py` парсит входящие MQTT-сообщения и генерирует события, `bridge.py` реагирует на них и вызывает `wb/publisher.py`. Обратный путь: `wb/subscriber.py` получает команды из WB и передаёт в `bridge.py`, который публикует в z2m.
- **Минимум зависимостей**: только `paho-mqtt`, никаких фреймворков.

---

## 5. Структура системы (Building Blocks)

### Уровень 1

```
┌──────────────────────────────────────────────┐
│              wb-zigbee2mqtt-v2               │
│                                              │
│  main.py → app.py (WbZigbee2Mqtt)            │
│                    │                         │
│              bridge.py (оркестратор)         │
│              ┌─────┴─────┐                   │
│        ┌─────┴──┐  ┌─────┴───────┐           │
│        │  z2m/  │  │wb_converter/│           │
│        └────────┘  └─────────────┘           │
│              wb_common.MQTTClient            │
└──────────────────────────────────────────────┘
```

### Уровень 2 — модули

| Модуль | Ответственность | Статус |
|---|---|---|
| `main.py` | Точка входа: `setup_logging()`, парсинг CLI, загрузка конфига | ✅ |
| `app.py` | `WbZigbee2Mqtt`: MQTT-клиент, сигналы, жизненный цикл, коды выхода | ✅ |
| `config_loader.py` | Загрузка и валидация JSON-конфига (dataclass `ConfigLoader`) | ✅ |
| `bridge.py` | Оркестратор: z2m-события → WB-контролы, регистрация/удаление устройств | ✅ |
| `registered_device.py` | `RegisteredDevice`: кеш z2m-устройства с WB controls и device_id | ✅ |
| `z2m/client.py` | `Z2MClient`: подписка на z2m-топики, парсинг → коллбэки | ✅ |
| `z2m/model.py` | `BridgeInfo`, `BridgeState`, `DeviceEvent`, `BridgeLogLevel`, `Z2MDevice`, `ExposeFeature`, `ExposeType`, `ExposeProperty` | ✅ |
| `mqtt_client.py` | Зарезервировано для расширения MQTT-клиента | зарезервировано |
| `z2m/ota.py` | OTA: проверка и запуск обновлений | зарезервировано |
| `wb_converter/publisher.py` | `WbPublisher`: публикация/удаление устройств, JSON `/meta`, команды | ✅ |
| `wb_converter/expose_mapper.py` | Маппинг z2m exposes → WB `ControlMeta` (10 numeric типов, binary, enum, text) | ✅ |
| `wb_converter/subscriber.py` | Подписка на `/on`-топики WB, передача команд в bridge | зарезервировано |
| `wb_converter/controls.py` | `WbControlType`, `BridgeControl`, `ControlMeta` (с `format_value`), `BRIDGE_CONTROLS` | ✅ |

---

## 6. Динамика (Runtime View)

### Старт сервиса

```
main.py
  → загружает wb-zigbee2mqtt.conf (JSON)
  → создаёт WbZigbee2Mqtt (app.py)
    → создаёт MQTTClient, Bridge
    → подключается к брокеру

on_connect (первое подключение):
  → bridge.subscribe()
    → публикует WB-устройство моста (meta + начальные значения 10 контролов)
    → z2m_client подписывается на 6 топиков (state, info, logging, devices, event, response/device/remove)
    → подписывается на WB-команды (permit_join, update_devices)

on_connect (реконнект):
  → bridge.republish()
    → перепубликует meta и контролы моста
```

### Обновление состояния устройства

#### Идентификация устройств: `ieee_address` vs `friendly_name`

WB `device_id` формируется из `ieee_address` (не `friendly_name`), потому что:
- `ieee_address` гарантированно уникален (аппаратный адрес)
- не меняется при переименовании устройства в z2m
- исключает коллизии (например `"sensor-1"` и `"sensor.1"` дали бы одинаковый `device_id`)

Где что используется:
- `ieee_address` → WB `device_id`, MQTT-топики WB (`/devices/{ieee_address}/controls/...`)
- `friendly_name` → отображаемое имя (title) в WB UI, подписка на z2m топики (`zigbee2mqtt/{friendly_name}`), ключ в `_known_devices`

```
zigbee2mqtt/{friendly_name} (входящее сообщение)
  → z2m/client.py парсит JSON
  → bridge.py получает событие device_state_changed
  → wb/publisher.py публикует /devices/{ieee_address}/controls/{control}
```

### Команда из WB

По WB MQTT Conventions топик `/on` — это канал для входящих команд:
сервис подписывается на него и реагирует на действия пользователя (веб-интерфейс, другой клиент).
Задача сервиса — получить команду из `/on`-топика и транслировать её в соответствующий топик zigbee2mqtt.

```
/devices/{ieee_address}/controls/{control}/on (входящее сообщение от пользователя)
  → wb/subscriber.py получает команду
  → bridge.py маппит WB-контрол → z2m атрибут
  → mqtt_client публикует zigbee2mqtt/{friendly_name}/set {"attribute": value}
```

### Удаление устройства

Обрабатывается при событиях `device_removed` и `device_leave`:

```
zigbee2mqtt/bridge/event → {"type": "device_removed", ...}
  → bridge.py удаляет устройство из _known_devices
  → z2m/client.py (unsubscribe_device) снимает подписку с zigbee2mqtt/{friendly_name}
  → wb/publisher.py (remove_device) публикует пустые retain "" на все топики WB-устройства
  → устройство исчезает из WB UI
```

Также обрабатывается `bridge/response/device/remove` (ответ на команду удаления).

### Переименование устройства

Обрабатывается двумя способами (z2m может использовать любой):

1. Событие `bridge/event` с `type: "device_renamed"` — содержит `from` и `to`
2. Переопубликация `bridge/devices` — `_register_device` обнаруживает, что `ieee_address` уже известен под другим `friendly_name`

```
zigbee2mqtt/bridge/devices → устройство с новым friendly_name
  → bridge.py находит старое имя по ieee_address (_find_old_name)
  → z2m/client.py (unsubscribe_device) снимает подписку со старого топика
  → z2m/client.py (subscribe_device) подписывается на новый топик
  → wb/publisher.py (publish_device) обновляет title в WB
  → device_id (ieee_address) не меняется — WB-устройство остаётся тем же
```

### Известные ограничения

- Если устройство обновило firmware (OTA) и exposes изменились, новые контролы не появятся до перезапуска сервиса
- Устройства, у которых все exposes неизвестного типа, не регистрируются (только `last_seen` недостаточно)

---

## 7. Развёртывание (Deployment View)

```
Wiren Board (ARM Linux)
├── /usr/lib/python3/dist-packages/wb/zigbee2mqtt/        — Python-пакет
├── /usr/lib/wb-zigbee2mqtt/configs/wb-zigbee2mqtt.conf   — конфигурация (JSON)
└── /lib/systemd/system/wb-zigbee2mqtt.service            — systemd unit

Зависимости на целевой системе:
- python3.9
- python3-wb-common (>= 2.1.0) — включает paho-mqtt
- MQTT broker (mosquitto, уже установлен на WB)
- zigbee2mqtt (устанавливается отдельно)
```

---

## 8. Сквозные концепции (Cross-cutting Concepts)

### Переподключение к MQTT

`wb_common.MQTTClient` реализует автоматическое переподключение при разрыве. После восстановления соединения `app.py` вызывает `bridge.republish()` для перепубликации meta и контролов моста. Подписки MQTT-клиент восстанавливает автоматически.

### Динамические контролы WB

WB MQTT Conventions позволяют добавлять и удалять контролы в runtime через retain-сообщения на мета-топики. Это используется для:
- создания контролов при обнаружении устройства
- показа/скрытия OTA-контролов в зависимости от состояния
- удаления всех контролов при удалении устройства

### Совместимость z2m v1.x / v2.x

Версия z2m определяется из `bridge/info` или `bridge/config`. Поведение, зависящее от версии (permit_join payload), инкапсулировано в `z2m/client.py`.

### Логирование

Используется стандартный `logging` Python. В systemd-окружении вывод идёт в journald (`journalctl -u wb-zigbee2mqtt`).

---

## 9. Архитектурные решения

| Решение | Обоснование |
|---|---|
| Python 3.9 вместо JS/wb-rules | Тестируемость, читаемость, независимость от движка wb-rules |
| paho-mqtt без фреймворков | Минимум зависимостей, контроль над логикой переподключения |
| `exposes` вместо захардкоженных маппингов | Автоматическая поддержка новых устройств и writable-контролов |
| systemd-сервис | Стандартный способ управления сервисами на WB |
| Один MQTT-клиент для z2m и WB | Оба брокера — один и тот же mosquitto на WB |

---

## 10. Требования к качеству

| Атрибут | Требование |
|---|---|
| Надёжность | Автоматическое восстановление после потери MQTT-соединения |
| Актуальность данных | Состояние устройств запрашивается через `/get` при старте, далее — в реальном времени |
| Сопровождаемость | Покрытие тестами, статический анализ (pylint), автоформатирование (black, isort) |
| Совместимость | Работа с zigbee2mqtt v1.x и v2.x |

---

## 11. Риски и технический долг

| Риск | Описание | Митигация |
|---|---|---|
| Сложность `exposes` | Вложенные composite/specific features могут давать неожиданные структуры | Итеративная разработка на реальных устройствах |
| Миграция с v1 | Имена WB-устройств и контролов могут измениться — сломаются правила пользователей | См. открытый вопрос о миграции |
| Группы без `exposes` | У групп нет схемы — используется фиксированный набор контролов | Можно расширить позже |

---

## 12. Глоссарий

| Термин | Определение |
|---|---|
| **zigbee2mqtt** | Open-source шлюз, который подключает Zigbee-устройства к MQTT-брокеру |
| **WB MQTT Conventions** | Соглашение Wiren Board о структуре MQTT-топиков для устройств и контролов |
| **exposes** | Схема, которую zigbee2mqtt публикует для каждого устройства: список атрибутов, типы, права доступа |
| **wb-rules** | Движок правил Wiren Board, выполняет JS-скрипты для автоматизации |
| **контрол** | Единица данных в WB MQTT Conventions: одно значение с типом, единицей измерения и правами доступа |
| **retain** | Флаг MQTT-сообщения: брокер хранит последнее значение и отдаёт новым подписчикам сразу |
| **OTA** | Over-the-air — обновление прошивки устройства по воздуху через zigbee2mqtt |
