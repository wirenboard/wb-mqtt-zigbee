# План тестирования wb-mqtt-zigbee

## 1. Юнит-тесты конвертации значений

Файл: `tests/unit/test_format_value.py`

Проверяем `ControlMeta.format_value()` (z2m → WB) и `ControlMeta.parse_wb_value()` (WB → z2m).

### 1.1 Switch (binary)

| z2m значение | value_on/off | format_value → WB | parse_wb_value("1") → z2m | parse_wb_value("0") → z2m |
|---|---|---|---|---|
| `"ON"` | `"ON"` / `"OFF"` | `"1"` | `"ON"` | `"OFF"` |
| `"OFF"` | `"ON"` / `"OFF"` | `"0"` | `"ON"` | `"OFF"` |
| `true` | — | `"1"` | `True` | `False` |
| `false` | — | `"0"` | `True` | `False` |
| `"toggle"` | `"toggle"` / `"off"` | `"1"` | `"toggle"` | `"off"` |

### 1.2 Numeric (value / range)

| z2m значение | format_value → WB | WB значение | parse_wb_value → z2m |
|---|---|---|---|
| `23.5` | `"23.5"` | `"23.5"` | `23.5` |
| `100` | `"100"` | `"100"` | `100` (int, не float) |
| `0` | `"0"` | `"0"` | `0` |
| `254` (brightness) | `"254"` | `"200"` | `200` |
| `-10.3` | `"-10.3"` | `"-10.3"` | `-10.3` |

### 1.3 RGB (color)

| z2m значение (HS dict) | format_value → WB | WB значение | parse_wb_value → z2m |
|---|---|---|---|
| `{"hue": 0, "saturation": 100}` | `"255;0;0"` | `"255;0;0"` | `{"hue": 0, "saturation": 100}` |
| `{"hue": 240, "saturation": 100}` | `"0;0;255"` | `"0;0;255"` | `{"hue": 240, "saturation": 100}` |
| `{"hue": 120, "saturation": 100}` | `"0;255;0"` | `"0;255;0"` | `{"hue": 120, "saturation": 100}` |
| `{"hue": 0, "saturation": 0}` | `"255;255;255"` | `"255;255;255"` | `{"hue": 0, "saturation": 0}` |

### 1.4 Text / Enum

| z2m значение | format_value → WB | WB значение | parse_wb_value → z2m |
|---|---|---|---|
| `"auto"` | `"auto"` | `"auto"` | `"auto"` |
| `"heat"` | `"heat"` | `"heat"` | `"heat"` |
| `""` | `""` | `""` | `""` |

### 1.5 Edge cases

| Сценарий | format_value | parse_wb_value |
|---|---|---|
| `None` | `""` | — |
| `bool True` (без value_on) | `"1"` | — |
| `bool False` (без value_on) | `"0"` | — |
| `dict` (не color) | JSON-строка | — |
| Невалидное число (`"abc"`) | — | исходная строка `"abc"` |
| Пустая строка (numeric) | — | `""` |

### 1.6 Round-trip

Для каждого типа: `parse_wb_value(format_value(z2m_value))` должен давать эквивалентное значение (с точностью до типа).

Проверяемые типы: switch (с value_on/off), numeric, rgb, text.

---

## 2. Юнит-тесты маппинга exposes → контролы

Файл: `tests/unit/test_expose_mapper.py`

Проверяем `map_exposes_to_controls()` и вспомогательные функции.

### 2.1 Leaf features

| z2m expose | Ожидаемый WB тип | readonly | Доп. поля |
|---|---|---|---|
| `numeric`, property=`temperature`, access=READ | `temperature` | `True` | — |
| `numeric`, property=`humidity`, access=READ | `rel_humidity` | `True` | — |
| `numeric`, property=`brightness`, access=READ+WRITE, min=0, max=254 | `range` | `False` | min=0, max=254 |
| `numeric`, property=`brightness`, access=READ+WRITE, без min/max | `value` | `False` | — |
| `numeric`, property=`unknown_prop`, access=READ | `value` | `True` | — |
| `binary`, property=`state`, value_on=`"ON"`, value_off=`"OFF"`, access=RW | `switch` | `False` | value_on, value_off |
| `binary`, property=`occupancy`, access=READ | `switch` | `True` | value_on, value_off |
| `enum`, property=`mode`, values=`["off","auto","heat"]` | `text` | зависит от access | enum=`{"off":0,"auto":1,"heat":2}` |
| `text`, property=`effect` | `text` | зависит от access | — |
| Пустой property=`""` | — (пропускается) | — | — |

Дополнительно: проверка всех 10 маппингов NUMERIC_TYPE_MAP (`temperature`, `humidity`, `pressure`, `co2`, `noise`, `power`, `voltage`, `current`, `energy`, `illuminance_lux`).

### 2.2 Composite features

| z2m expose | Ожидаемый результат |
|---|---|
| `light` с вложенными `state` + `brightness` + `color_temp` + `color` | 4 контрола: switch + range + range + rgb |
| `composite` color с `hue` + `saturation` | 1 контрол `rgb` (property=`color`) |
| `switch` с вложенным `state` | 1 контрол: switch |

### 2.3 Сервисные контролы

| Условие | Ожидаемый результат |
|---|---|
| device_type=`"Router"` | контрол `device_type` (text, readonly) добавлен |
| device_type=`""` | контрол `device_type` не добавлен |
| Всегда | контрол `last_seen` (text, readonly) добавлен последним |

### 2.4 Order и дедупликация

| Сценарий | Ожидаемый результат |
|---|---|
| Несколько exposes | order назначается последовательно начиная с 1 |
| Два expose с одинаковым property | второй игнорируется, первый сохраняется |

### 2.5 Полные устройства

Проверка на готовых фикстурах: датчик температуры (temperature + humidity + battery + device_type + last_seen), мультисенсор (4 expose + last_seen), цветная лампа (state + brightness + color_temp + color + device_type + last_seen).

---

## 3. Интеграционные тесты с мок-брокером

Файл: `tests/integration/test_bridge_mock.py`

Тестируем полный цикл прохождения данных через Bridge + WbPublisher + Z2MClient с мок-MQTT-клиентом (без сети).

### 3.1 Чтение состояния устройства (z2m → WB)

| Сценарий | Действие | Проверка |
|---|---|---|
| Реле ON | inject `{"state": "ON"}` | контрол `state` = `"1"` |
| Реле OFF | inject `{"state": "OFF"}` | контрол `state` = `"0"` |
| Датчик температуры | inject `{"temperature": 23.5, "humidity": 65}` | контролы = `"23.5"`, `"65"` |
| Тип устройства Router | регистрация устройства | `device_type` = `"Маршрутизатор"` |
| Тип устройства EndDevice | регистрация устройства | `device_type` = `"Оконечное устройство"` |
| Цветная лампа | inject `{"color": {"hue": 0, "saturation": 100}}` | `color` = `"255;0;0"` |
| last_seen (epoch ms) | inject `{"last_seen": 1700000000000}` | непустая строка с `"2023"` |
| Неизвестное устройство | inject state для незарегистрированного | нет callback, игнорируется |
| Без exposes | `bridge/devices` с `definition: null` | устройство не регистрируется |
| Meta контролов | регистрация реле | meta содержит `type`, `readonly` |
| Range meta | регистрация лампы | brightness meta содержит `min`, `max` |

### 3.2 Управление устройством (WB → z2m)

| Сценарий | WB команда | Ожидаемый z2m payload |
|---|---|---|
| Реле вкл | `/on` = `"1"` | `{"state": "ON"}` |
| Реле выкл | `/on` = `"0"` | `{"state": "OFF"}` |
| Яркость | `/on` = `"200"` | `{"brightness": 200}` |
| Цвет | `/on` = `"255;0;0"` | `{"color": {"hue": 0, "saturation": 100}}` |
| Readonly не подписан | — | нет callback на `/on` для readonly контрола |

### 3.3 Жизненный цикл устройства

| Сценарий | Действие | Проверка |
|---|---|---|
| Регистрация | `bridge/devices` | device meta с title, control meta опубликованы |
| Переименование (event) | `bridge/event` → `device_renamed` | подписка на новый z2m-топик, title обновлён |
| Переименование (devices) | `bridge/devices` с новым friendly_name | обнаружение по ieee_address, title обновлён |
| Удаление (response) | `bridge/response/device/remove` | retain-сообщения очищены (`""`) |
| Удаление (leave) | `bridge/event` → `device_leave` | retain-сообщения очищены |
| Команды после переименования | `/on` после rename | z2m/set идёт на новый friendly_name |
| Несколько устройств | 2 устройства одновременно | состояния независимы |

### 3.4 Устройство моста

| Сценарий | Действие | Проверка |
|---|---|---|
| Состояние (строка) | `bridge/state` = `"online"` | `State` = `"online"` |
| Состояние (JSON) | `bridge/state` = `{"state": "online"}` | `State` = `"online"` |
| Информация | `bridge/info` с version, permit_join | `Version`, `Permit join` обновлены |
| Permit join вкл | `/on` = `"1"` | `{"time": 254}` в request/permit_join |
| Permit join выкл | `/on` = `"0"` | `{"time": 0}` в request/permit_join |
| Фильтрация < min | `bridge/logging` level=info (min=warning) | контрол Log НЕ обновляется |
| Фильтрация = min | `bridge/logging` level=warning | контрол Log обновляется |
| Фильтрация > min | `bridge/logging` level=error | контрол Log обновляется |
| Счётчик устройств | `bridge/devices` с 2 устройствами | `Device count` = `"2"` |
| Обновление устройств | `/on` для Update devices | publish в request/devices/get |

---

## 4. Интеграционные тесты на тестовом стенде (read-only)

Файл: `tests/integration/test_bridge_hw.py`

Подключаемся к реальному MQTT-брокеру на контроллере и проверяем структуру опубликованных топиков. **Только чтение — ничего не пишем, безопасно для любого стенда.**

### 4.1 Устройство моста

| Проверка |
|---|
| `/devices/zigbee2mqtt/meta` существует и содержит `title` |
| Все 12 контролов присутствуют (State, Version, Permit join, ..., Log) |
| `State` = `"online"` |
| `Version` непустой |
| `Device count` > 0 |
| Каждый control meta содержит `type`, `readonly`, `order` |
| Типы контролов совпадают с ожидаемыми (State→text, Permit join→switch, ...) |
| `Permit join` — `readonly: false` |

### 4.2 Zigbee-устройства

| Проверка |
|---|
| Найдено хотя бы одно устройство с `device_id` начинающимся на `0x` |
| Каждое устройство имеет `/meta` с `title` |
| У каждого устройства есть хотя бы один контрол |
| Каждый control meta содержит `type` и `readonly` |
| Все `type` из допустимого набора (value, switch, text, temperature, range, rgb, ...) |
| Каждое устройство имеет контрол `last_seen` |
| Каждое устройство имеет контрол `device_type` |
| Значения `device_type` из допустимого набора (Маршрутизатор, Оконечное устройство, ...) |
| Контролы типа `range` имеют `min` или `max` в meta |
| У каждого контрола с meta есть топик значения |

---

## Инфраструктура

### Фреймворк

pytest 7.4+

### Структура

```
tests/
├── conftest.py                      # общие фикстуры, тестовые exposes, --teststand-host
├── unit/
│   ├── test_format_value.py         # ControlMeta.format_value / parse_wb_value (47 тестов)
│   └── test_expose_mapper.py        # map_exposes_to_controls (22 теста)
└── integration/
    ├── conftest.py                  # MockMQTTClient, фикстура bridge, тестовые устройства
    ├── test_bridge_mock.py          # полный цикл через мок MQTTClient (34 теста)
    └── test_bridge_hw.py            # read-only проверки на тестовом стенде (19 тестов)
```

### Заглушка wb_common

Библиотека `wb_common` (paho-mqtt обёртка) не установлена в dev-окружении. В `tests/conftest.py` автоматически подставляется MagicMock-заглушка через `sys.modules`, чтобы импорты проекта не падали.

### MockMQTTClient

Файл: `tests/integration/conftest.py`

Мок `wb_common.MQTTClient` для интеграционных тестов без сети:

| Метод | Поведение |
|---|---|
| `publish(topic, payload, retain, qos)` | Записывает в `published` (список), при `retain=True` также в `retained` (словарь) |
| `subscribe(topic)` | Добавляет в `subscriptions` (set) |
| `unsubscribe(topic)` | Удаляет из `subscriptions` |
| `message_callback_add(topic, cb)` | Регистрирует callback в `callbacks` (dict) |
| `message_callback_remove(topic)` | Удаляет callback |

Хелперы:
- `inject_message(topic, payload)` — создаёт `FakeMessage`, вызывает зарегистрированный callback синхронно
- `find_published(topic)` — возвращает все payload, опубликованные в указанный топик
- `get_control_value(device_id, control_id)` — значение из retained
- `get_control_meta(device_id, control_id)` — JSON meta из retained

### MQTTReader (HW тесты)

Файл: `tests/integration/test_bridge_hw.py`

Подключается к реальному MQTT-брокеру через `paho.mqtt.client`, подписывается на топики и собирает retained-сообщения. Метод `subscribe_and_wait(topic, timeout)` фильтрует результаты по паттерну подписки.

### Тестовые устройства

Готовые expose-словари и JSON для `bridge/devices`:

| Фикстура | Описание | Где определена |
|---|---|---|
| `RELAY_EXPOSE` / `RELAY_DEVICE` | Реле (switch → binary state ON/OFF, writable) | `tests/conftest.py` / `tests/integration/conftest.py` |
| `TEMP_SENSOR_EXPOSES` / `TEMP_SENSOR_DEVICE` | Датчик температуры (temperature + humidity + battery, readonly) | там же |
| `COLOR_LAMP_EXPOSES` / `COLOR_LAMP_DEVICE` | Цветная лампа (state + brightness + color_temp + color, writable) | там же |
| `ENUM_EXPOSE` | Enum контрол (mode: off/auto/heat/cool) | `tests/conftest.py` |
| `MULTISENSOR_EXPOSES` | Мультисенсор (temperature + humidity + illuminance + occupancy) | `tests/conftest.py` |

### Запуск

```bash
# Юнит-тесты (быстро, без зависимостей)
pytest tests/unit/

# Интеграционные с мок-брокером (быстро, без зависимостей)
pytest tests/integration/test_bridge_mock.py

# Все локальные тесты (юнит + мок)
pytest tests/

# Тесты на тестовом стенде (read-only, требует paho-mqtt и доступ к контроллеру)
pytest tests/integration/test_bridge_hw.py --teststand-host=192.168.88.99

# Всё вместе
pytest tests/ --teststand-host=192.168.88.99

# Verbose вывод
pytest tests/ -v
```

Без `--teststand-host` тесты со стенда автоматически пропускаются (skip).

---

## Как добавлять новые тесты

### Новый тип контрола или конвертация

1. Добавить тест-кейсы в `tests/unit/test_format_value.py` — в соответствующий класс (`TestSwitchFormatValue`, `TestNumericParseWbValue`, и т.д.) или создать новый класс для нового типа
2. Если нужны новые expose-фикстуры — добавить словарь в `tests/conftest.py` и pytest-фикстуру
3. Обновить таблицы в этом документе (разделы 1.x)

### Новый маппинг expose → контрол

1. Добавить тест в `tests/unit/test_expose_mapper.py` — в `TestLeafFeatures` для leaf, `TestCompositeFeatures` для composite
2. Если добавлен новый тип в `NUMERIC_TYPE_MAP` — добавить в `test_all_numeric_types`
3. Обновить таблицы (разделы 2.x)

### Новый сценарий интеграции (мок)

1. Добавить тестовое устройство в `tests/integration/conftest.py` (словарь формата `bridge/devices`)
2. Добавить тест в `tests/integration/test_bridge_mock.py` — в соответствующий класс (`TestReadState`, `TestDeviceControl`, `TestDeviceLifecycle`, `TestBridgeDevice`)
3. Используй хелпер `register_device(mock_mqtt, DEVICE_DICT)` для регистрации устройства
4. Обновить таблицы (разделы 3.x)

### Новый HW тест

1. Добавить в `tests/integration/test_bridge_hw.py` в класс `TestBridgeDevice` (мост) или `TestZigbeeDevices` (устройства)
2. Тест **должен быть read-only** — только чтение MQTT-топиков, без записи
3. Использовать фикстуры `mqtt_reader`, `bridge_controls`, `zigbee_devices`
4. Обновить таблицы (раздел 4.x)

### Общие правила

- Тестовые данные (expose-словари, device JSON) — в conftest-файлах, не в тестах
- Юнит-тесты не требуют MockMQTTClient — работают напрямую с `ControlMeta` и `ExposeFeature`
- Интеграционные тесты используют `inject_message()` для имитации входящих MQTT-сообщений
- Новый тип контрола в `WbControlType` → добавить в `valid_types` в `test_control_types_are_valid`
