# Тестирование

Документ описывает автоматизированный тестовый набор `wb-mqtt-zigbee`: локальное окружение, как запускать, как снимать coverage, что покрыто.


## Подготовка окружения

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r dev-requirements.txt
```

`pip install -e .` ставит пакет в editable-режиме, чтобы тесты могли делать `import wb.mqtt_zigbee` без отдельной настройки `PYTHONPATH`.

Зависимости для разработки закреплены в [`dev-requirements.txt`](../dev-requirements.txt).


## Структура

```
tests/
├── __init__.py                 # делает tests пакетом для pytest discovery
├── conftest.py                 # общие фикстуры (сейчас пустой; оставлен под общие фикстуры между unit и integration)
├── README.md                   # этот файл
├── unit/                       # unit-тесты (без I/O)
│   ├── __init__.py
│   ├── test_config_loader.py
│   ├── test_controls.py
│   ├── test_expose_mapper.py
│   ├── test_model.py
│   └── test_registered_device.py
└── integration/                # интеграционные тесты (с моком MQTT-брокера)
    ├── __init__.py
    ├── conftest.py             # фикстуры + stub `wb_common.mqtt_client`
    ├── fakes/
    │   ├── broker.py           # FakeMqttBroker
    │   └── client.py           # FakeMqttClient
    ├── helpers/                # обёртки для тестов
    │   ├── wb_observer.py      # выборки из publish_log/retained
    │   └── z2m_emulator.py     # публикует z2m-shaped сообщения
    ├── test_fake_broker.py     # самотесты мока
    ├── test_z2m_client.py      # уровень 1: Z2MClient
    ├── test_wb_publisher.py    # уровень 2: WbMqttDriver
    ├── test_bridge_e2e.py      # уровень 3: Bridge end-to-end
    └── test_app_lifecycle.py   # уровень 4: WbZigbee2Mqtt connect/disconnect/reconnect
```

Отдельного pytest-конфига в проекте нет: pytest сам находит тесты через auto-discovery от корня репозитория, а корень попадает в `sys.path` за счёт `tests/__init__.py` (rootdir-механизм pytest), так что `import wb.mqtt_zigbee` работает без `pip install -e .`. Пакеты `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py` также нужны для относительных импортов хелперов и фейков. Зависимости для запуска — `pytest` и `paho-mqtt` (для прод-кода `z2m/client.py` и `wb_converter/publisher.py`); обе закреплены в `dev-requirements.txt`.


## Запуск

Из корня репозитория:

```bash
# Весь набор
pytest tests/

# Только unit-тесты
pytest tests/unit

# Только интеграционные
pytest tests/integration

# Конкретный файл, с подробным выводом
pytest tests/unit/test_expose_mapper.py -v

# Фильтр по имени теста/класса (подстрока)
pytest tests/ -k "rgb"
pytest tests/ -k "TestFlattenExpose"

# Остановиться на первой ошибке, показать локальные переменные
pytest tests/ -x --showlocals
```


## Coverage

Coverage снимается через [`pytest-cov`](https://pytest-cov.readthedocs.io/) (обёртка над `coverage.py`). Версия закреплена в `dev-requirements.txt` и ставится при `pip install -r dev-requirements.txt` из шага «Подготовка окружения».

Coverage не включён в опции pytest по умолчанию — чистый `pytest tests/` остаётся быстрым. Запускается явно, когда нужен.

### Три варианта запуска

В зависимости от того, что именно хочется увидеть:

**1. Общая картина по всему пакету.**

```bash
pytest --cov=wb.mqtt_zigbee --cov-report=term-missing tests/
```

**2. Один подпакет.**

```bash
pytest --cov=wb.mqtt_zigbee.wb_converter --cov-report=term-missing tests/
```

**3. Один модуль (+ его тест-файл).**

```bash
pytest --cov=wb.mqtt_zigbee.wb_converter.expose_mapper \
       --cov-report=term-missing \
       tests/unit/test_expose_mapper.py
```

### Форматы отчёта

- `term-missing` (в примерах выше) — процент + номера непокрытых строк прямо в терминале. Удобно для итеративной работы: видно, куда нести следующий тест.
- `html` — кликабельное дерево в `htmlcov/`, полезно при разрастании проекта:
  ```bash
  pytest --cov=wb.mqtt_zigbee --cov-report=html tests/
  xdg-open htmlcov/index.html
  ```
- `term` (без `missing`) — только проценты, компактнее, но теряется самое полезное.

### Текущее состояние

С учётом unit- и integration-тестов:

```
Module                                          Stmts  Miss  Cover
------------------------------------------------------------------
wb/mqtt_zigbee/__main__.py                          3     3     0%
wb/mqtt_zigbee/app.py                              57    11    81%
wb/mqtt_zigbee/bridge.py                          268    48    82%
wb/mqtt_zigbee/config_loader.py                    37     0   100%
wb/mqtt_zigbee/main.py                             21    21     0%
wb/mqtt_zigbee/registered_device.py                14     0   100%
wb/mqtt_zigbee/wb_converter/controls.py           106     0   100%
wb/mqtt_zigbee/wb_converter/expose_mapper.py       64     0   100%
wb/mqtt_zigbee/wb_converter/publisher.py          149     3    98%
wb/mqtt_zigbee/z2m/client.py                      146     6    96%
wb/mqtt_zigbee/z2m/model.py                       105     0   100%
------------------------------------------------------------------
TOTAL                                             970    92    91%
```

Вся «чистая» (без I/O) логика покрыта на 100% unit-тестами. Модули с MQTT-коллбэками (`z2m/client.py`, `wb_converter/publisher.py`, `bridge.py`, `app.py`) покрыты интеграционными тестами через `FakeMqttBroker` — 81–98%.

Непокрытые строки — это:

- `__main__.py` и `main.py` — точки входа CLI, исполняются только при реальном запуске сервиса.
- одиночные ветки error-handling и `__repr__`-помощники в `app.py`/`bridge.py`/`z2m/client.py`/`publisher.py`, которые не воспроизводимы без реального брокера или специально сконструированных broken-payload'ов; ценность отдельных тестов на них не оправдывает шум.


## Общие соглашения

### Фабрика `make_expose()`

Все тесты, работающие с `ExposeFeature`, создают его через фабрику в начале файла. По умолчанию возвращает читаемый numeric-лист; каждый тест переопределяет только те поля, которые важны именно ему:

```python
# Лист «по умолчанию»
make_expose(property="temperature")

# Writable numeric с диапазоном
make_expose(
    type=ExposeType.NUMERIC,
    property="brightness",
    access=WRITABLE,
    value_min=0,
    value_max=254,
)

# Композитный color
make_expose(
    type=ExposeType.COMPOSITE,
    property="color",
    features=[make_expose(property="x"), make_expose(property="y")],
)
```

Константы `READABLE` / `WRITABLE` оборачивают битовую маску `ExposeAccess` — чтобы в тестах читалось назначение, а не магические числа.


## Что покрыто

Раздел растёт по мере появления новых тестов. Содержание идёт по тест-файлам. Тесты внутри каждого файла сгруппированы в классы `TestXxx` по тестируемой единице (см. `TESTING_GUIDE.md`).

### `tests/unit/test_expose_mapper.py`

Проверяют [`wb/mqtt_zigbee/wb_converter/expose_mapper.py`](../wb/mqtt_zigbee/wb_converter/expose_mapper.py) — модуль, конвертирующий `exposes`-схему zigbee2mqtt в словарь метаданных WB MQTT-контролов. Это чистая функциональная логика (без I/O и состояния), и она покрыта на 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `map_exposes_to_controls` | `TestMapExposesToControls` | Сквозная нумерация `order` начиная с 1; дедупликация по `property` (первое вхождение побеждает); сервисные контролы `available` / `last_seen` добавляются всегда; `device_type` — только при непустом значении; `expose` без `property` пропускается, не ломая порядок. |
| `_flatten_expose` | `TestFlattenExpose` | Листовые фичи проходят как есть; сложные типы (`light`, `switch`, `climate` и др.) раскрываются рекурсивно, в том числе вложенные; `composite` с `property="color"` сворачивается в один RGB-контрол; композитный тип с пустым `features` падает в ветку листа. |
| `_map_leaf_feature` | `TestMapLeafFeature` | Пустой `property` → пустой результат; неизвестный `type` → пустой результат; numeric-свойства маппятся через `NUMERIC_TYPE_MAP` с фоллбеком на `value`; writable numeric `value` с обоими `min` и `max` маппятся в `range`, иначе остаётся `value`; типизированные numeric (`temperature` и т. п.) **не** будут `range` даже с min/max; binary → `switch` + `value_on`/`value_off`; enum → `text` + enum-словарь; text → `text`; `readonly` считается от `access & WRITE`; заголовок формируется из имени `property`. |
| `_map_color_feature` | `TestMapColorFeature` | Writable, если хотя бы один sub-feature writable, иначе readonly; пустой `features` → readonly; тип RGB; title имеют переводы на ru, en. |
| `_make_enum` | `TestMakeEnum` | `["off", "low", "high"]` → `{"off": 0, "low": 1, "high": 2}`; пустой список → `None`. |
| `_make_title` | `TestMakeTitle` | `snake_case` → `Snake case`; единичные слова; параметризованный тест. |
| `_resolve_wb_type` | `TestResolveWbType` | Все ветки (numeric known/unknown, binary, enum, text, unknown → `None`). |

### `tests/unit/test_controls.py`

Проверяют [`wb/mqtt_zigbee/wb_converter/controls.py`](../wb/mqtt_zigbee/wb_converter/controls.py) — модуль с типами WB-контролов, метаданными бридж-устройства и конверсией значений между WB MQTT и z2m. Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `_parse_number` | `TestParseNumber` | Целые и дробные числа; `5.0` → `int(5)`; отрицательные значения и ноль; научная нотация (`1e2` → `int(100)`); невалидные строки возвращаются как есть. |
| `_wb_rgb_to_hs_dict` | `TestWbRgbToHsDict` | Базовые цвета (R/G/B); белый и чёрный → нулевая насыщенность; параметризованный тест на невалидные форматы (пусто, неверное число компонент, нечисловые значения) → `{hue: 0, saturation: 0}`. |
| `_hs_dict_to_wb_rgb` | `TestHsDictToWbRgb` | Базовые цвета; нулевая насыщенность → белый; лишние ключи (`x`, `y`) игнорируются; отсутствие `hue`/`saturation` → дефолт `255;255;255`; невалидные типы значений → дефолт; числовые строки принимаются (через `float()`); roundtrip для основных цветов. |
| `ControlMeta.format_value` | `TestControlMetaFormatValue` | `None` → `""`; `bool` → `"1"`/`"0"`; `SWITCH` с `value_on` сравнивает строкой; `RGB` с dict идёт через `_hs_dict_to_wb_rgb`; прочий dict сериализуется в JSON; числа и строки — через `str()`; `bool` имеет приоритет над веткой `SWITCH+value_on`. |
| `ControlMeta.parse_wb_value` | `TestControlMetaParseWbValue` | `SWITCH` без `value_on` → `bool`; `SWITCH` с `value_on` → исходная строка z2m; `RGB` → HS-dict (включая фоллбек на дефолт при ошибке); `TEXT` возвращает строку как есть (даже `"123"`); все числовые типы (`VALUE`, `RANGE`, `TEMPERATURE`, `POWER`, …) идут через `_parse_number`; roundtrip `format → parse` для switch (bool и string режимы). |
| `ControlMeta` defaults | `TestControlMetaDefaults` | Дефолтные значения опциональных полей; `default_factory=dict` для `title` создаёт независимый словарь на каждый инстанс. |
| `BRIDGE_CONTROLS` | `TestBridgeControls` | Все ожидаемые ключи присутствуют; значения `order` уникальны и идут подряд от 1; у каждого контрола есть переводы `en` и `ru`; writable только `Permit join` и `Update devices`; `Permit join` — `switch`, `Update devices` — `pushbutton`. |

### `tests/unit/test_model.py`

Проверяют [`wb/mqtt_zigbee/z2m/model.py`](../wb/mqtt_zigbee/z2m/model.py) — дата-классы и константы, описывающие сущности zigbee2mqtt (устройства, expose-фичи, события, состояния бриджа). Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `_str_or_none` | `TestStrOrNone` | `None` остаётся `None`; строка возвращается как есть; числа и `bool` приводятся к строке (`1`, `"True"`, `"False"`); пустая строка не превращается в `None`. |
| `ExposeFeature.is_writable` | `TestExposeFeatureIsWritable` | `True`, если установлен бит `WRITE` (включая `READ|WRITE`); `False` для только `READ`, нулевого `access` и только `GET`. |
| `ExposeFeature.from_dict` | `TestExposeFeatureFromDict` | Полный лист со всеми полями; пустой dict даёт дефолты; `value_on`/`value_off` пропускаются через `_str_or_none` (включая `bool` → `"True"`/`"False"` и `None` → `None`); `enum` сохраняет `values`; `composite`/`light` рекурсивно парсит `features`, в т.ч. глубоко вложенные. |
| `Z2MDevice.from_dict` | `TestZ2MDeviceFromDict` | Полное устройство с `definition`; пустой dict; `definition: null` (z2m возвращает так для неподдерживаемых устройств) — модель/вендор/exposes пустые; `definition` отсутствует целиком; `definition` без `exposes`. |
| Defaults дата-классов | `TestDataclassDefaults` | `BridgeInfo` принимает обязательные поля; у `DeviceEvent.old_name` дефолт `""`; `default_factory` для `values`/`features`/`exposes` создаёт независимые контейнеры на каждый инстанс. |
| Константы-перечисления | `TestEnumLikeConstants` | Битовые значения `ExposeAccess`; строковые значения `BridgeState`, `DeviceAvailability`, `Z2MEventType`, `DeviceEventType`; все `ExposeType.*` — непустые уникальные строки. |
| `BridgeLogLevel` | `TestBridgeLogLevel` | `RANK` упорядочен `debug < info < warning < error`; покрывает все четыре уровня; строковые значения уровней. |

### `tests/unit/test_config_loader.py`

Проверяют [`wb/mqtt_zigbee/config_loader.py`](../wb/mqtt_zigbee/config_loader.py) — загрузка и валидация JSON-конфига `wb-mqtt-zigbee.conf`. Все тесты используют фикстуру `tmp_path` и хелпер `write_config()` для генерации временных файлов; походов в файловую систему за пределами `tmp_path` нет. Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| Успешная загрузка | `TestLoadConfigSuccess` | Минимальный конфиг (только обязательные ключи) применяет все дефолты; полный конфиг переопределяет каждый дефолт; `command_debounce_sec`, заданный целым, приводится к `float`; параметризованный тест на все 4 валидных значения `bridge_log_min_level`. |
| Ошибки загрузки | `TestLoadConfigErrors` | Несуществующий файл → `FileNotFoundError`; путь-директория тоже даёт `FileNotFoundError`; невалидный JSON → `ValueError("not valid JSON")`; отсутствие `broker_url` или `zigbee2mqtt_base_topic` → `ValueError("Missing required configuration key")`; нечисловой `command_debounce_sec` → `ValueError` от `float()`. |
| `_validate_log_level` | `TestValidateLogLevel` | Параметризованно для 4 валидных уровней — возвращаются как есть; неизвестный уровень → дефолт + warning в логе (через `caplog`); end-to-end через `load_config` — невалидный уровень в файле тоже падает на дефолт; пустая строка и uppercase (`"ERROR"`) считаются невалидными (z2m уровни — lowercase). |
| Дефолты-константы | `TestDefaults` | Значения `BRIDGE_DEVICE_ID_DEFAULT`, `BRIDGE_DEVICE_NAME_DEFAULT`, `BRIDGE_LOG_MIN_LEVEL_DEFAULT`, `COMMAND_DEBOUNCE_SEC_DEFAULT`. |

### `tests/unit/test_registered_device.py`

Проверяют [`wb/mqtt_zigbee/registered_device.py`](../wb/mqtt_zigbee/registered_device.py) — дата-классы `PendingCommand` и `RegisteredDevice` (внутренний кэш состояния устройства между MQTT-публикациями и командами). Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `PendingCommand` | `TestPendingCommand` | Сохранение полей; сравнение по значению (dataclass-equality). |
| `RegisteredDevice` | `TestRegisteredDevice` | Дефолты `pending_commands={}` и `availability_received=False`; `default_factory` для `pending_commands` создаёт независимый словарь на каждый инстанс; принимает переопределение всех полей; `controls` хранится по ссылке (мутации видны в инстансе). |

## Интеграционные тесты

Расположены в `tests/integration/`. Заменяют MQTT-брокер на in-process `FakeMqttBroker` (без сети, без потоков, без Docker) — пригодно для запуска в Jenkins без специального окружения. `FakeMqttClient` — drop-in замена `wb_common.mqtt_client.MQTTClient` с подмножеством API, которое реально использует прод-код (`subscribe`, `unsubscribe`, `publish`, `message_callback_add/remove`, атрибутные коллбэки `on_connect`/`on_disconnect`).

Пакет `wb_common` поставляется отдельным Debian-пакетом и не доступен в pip. Если он не установлен, `tests/integration/conftest.py` подменяет `wb_common.mqtt_client` модулем-стабом через `sys.modules` — нужен только для аннотаций типов в прод-коде, в рантайме передаётся `FakeMqttClient` (никакого `isinstance` нет).

Каждый тест получает свежий брокер (function-scope фикстура `fake_broker`).

### `tests/integration/test_fake_broker.py`

Самотесты мока: фиксируют поведение, на которое опирается остальной набор. Если они падают, остальным тестам доверять нельзя.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `topic_matches` | `TestTopicMatches` | Точное совпадение, `+` (один уровень), `#` (хвост, ноль и более уровней); `#` валиден только в конце; разная глубина без wildcard'ов даёт `False`. |
| Retained semantics | `TestRetained` | `retain=True` сохраняет последний payload и перезаписывает предыдущий; пустой payload с `retain=True` удаляет retained-запись; новые подписчики получают retained при `message_callback_add`. |
| Subscribe / publish / inject | `TestRouting` | Publish доходит до подписчика (включая собственные publish'и); `inject` не пишет в `publish_log`; `unsubscribe` + `message_callback_remove` прекращают доставку; несколько подписок на один топик все срабатывают. |
| `publish_log` | `TestPublishLog` | Каждый клиентский publish записан с (`topic`, `payload`, `retain`, `qos`). |

### `tests/integration/test_z2m_client.py`

Проверяют [`wb/mqtt_zigbee/z2m/client.py`](../wb/mqtt_zigbee/z2m/client.py): подписки на топики `<base>/bridge/...` и `<base>/+/availability`, парсинг входящих JSON, исходящие команды (`set_permit_join`, `request_device_state`, `set_device_state`, `subscribe_device`).

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `bridge/state` | `TestBridgeState` | plain-string (`online`/`offline`/`error`) и JSON-обёртка `{"state": "..."}`; неизвестное значение игнорируется. |
| `bridge/info` | `TestBridgeInfo` | Полный payload даёт `BridgeInfo`; пустой даёт дефолты; невалидный JSON не вызывает callback. |
| `bridge/logging` | `TestBridgeLog` | Корректный JSON разбирается; payload-не-JSON фоллбачится на raw-текст и `level="info"`; отсутствующие ключи заполняются дефолтами. |
| `bridge/devices` | `TestBridgeDevices` | Список парсится в `Z2MDevice`; устройства с `type="Coordinator"` фильтруются; ошибка парсинга одного устройства не валит остальные; невалидный JSON игнорируется. |
| `bridge/event` | `TestBridgeEvent` | `device_joined` / `device_leave` / `device_renamed` мапятся в `DeviceEvent`; `friendly_name == ieee_address` приводит к использованию `ieee_address`; неизвестный тип события игнорируется. |
| `bridge/response/device/remove` | `TestRemoveResponse` | `status="ok"` создаёт `DeviceEventType.REMOVED`; `status="error"` игнорируется. |
| `+/availability` | `TestDeviceAvailability` | `<base>/<name>/availability` с `{"state":"online"}` → callback `(name, True)`; служебный `bridge/availability` игнорируется. |
| Per-device state | `TestPerDeviceState` | `state_topic` = `<base>/<name>` доставляет state-callbacks; парсинг JSON в dict. |
| Outgoing commands | `TestOutgoingCommands` | `set_permit_join(True/False)` публикует `{"time": 254}` или `{"time": 0}`; `set_device_state` сериализует payload в JSON; `request_device_state` шлёт пустой `{}`; `refresh_device_list` снимает и заново ставит подписку на `bridge/devices`. |
| Топология подписок | `TestSubscriptionTopology` | `subscribe_device` идемпотентен; `unsubscribe_device` без подписки no-op; начальные подписки покрывают `bridge/+`, `+/availability`. |

### `tests/integration/test_wb_publisher.py`

Проверяют [`wb/mqtt_zigbee/wb_converter/publisher.py`](../wb/mqtt_zigbee/wb_converter/publisher.py): публикацию виртуальных WB-устройств и контролов согласно WB MQTT Conventions (`/devices/<id>/...`).

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `publish_bridge_device` | `TestPublishBridgeDevice` | Публикует `meta` бриджа с `driver` и `title`; публикует `meta` для всех `BRIDGE_CONTROLS`; начальное значение каждого контрола — пробел; **все** publish'и идут с `retain=True, qos=1`. |
| Bridge controls | `TestPublishBridgeControl` | Запись в `Log` пушит retained payload в `<bridge>/controls/Log`. |
| `publish_device` / `publish_device_control` | `TestPublishDevice` | `meta` устройства и каждого контрола; `initial_values` подставляются (иначе пробел); устаревшие wb-rules-стиль топики (`meta/name`, `meta/driver`, `controls/<c>/meta/{type,order,readonly}`) затираются пустым retained. |
| `remove_device` / `remove_retained_device` | `TestRemoveDevice` | Все retained-записи устройства (`meta`, контролы, их `meta`, legacy-подтопики) затираются. |
| Bridge commands | `TestSubscribeBridgeCommands` | Подписка на `<bridge>/controls/Permit join/on` и `Update devices/on`; команда с payload `"1"`/`"0"` дёргает callback с правильным bool; pushbutton-команда дёргает callback без аргументов. |
| Device commands | `TestSubscribeDeviceCommands` | Подписка только на writable-контролы (readonly пропускаются); команда дёргает callback с `(control_id, value)`; `unsubscribe_device_commands` снимает только writable; после unsubscribe команда не доходит до callback. |
| `start_retained_scan` / `stop_retained_scan` | `TestRetainedScan` | Собирает только устройства с `driver == "wb-mqtt-zigbee"`; чужие драйверы фильтруются; bridge-устройство исключается; собирает per-device control_ids; невалидные/пустые `meta`-payload игнорируются; `stop_retained_scan` снимает wildcard-подписки; повторный `start` сбрасывает предыдущее состояние. |

### `tests/integration/test_bridge_e2e.py`

End-to-end проверки [`wb/mqtt_zigbee/bridge.py`](../wb/mqtt_zigbee/bridge.py) через единый `FakeMqttBroker`: входящие z2m-shaped сообщения переводятся в WB MQTT, исходящие WB-команды роутятся обратно в `<base>/<name>/set`. Время управляется фикстурой `fake_clock` через `monkeypatch.setattr` на `bridge_module.time.monotonic` — это позволяет детерминированно проверять 1Hz-throttling статистики и 5-секундный debounce pending-команд без реального ожидания.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| Инициализация | `TestBridgeInitialization` | `subscribe()` публикует `meta` бриджа, заполняет `Log level`, поднимает retained-scan; `bridge/state` → `controls/State`; `bridge/info` → `Version` и `Permit join`; `bridge/logging` ниже `min_level` не публикуется, на уровне и выше — публикуется. |
| Регистрация устройств | `TestDeviceRegistration` | Устройство из `bridge/devices` → `meta` + контролы в WB; `Device count` обновляется; `friendly_name` с `+`/`#`/`/` пропускается без падения. |
| Z2M → WB | `TestDeviceStatePropagation` | `<base>/<name>` (state) обновляет соответствующий контрол; `<base>/<name>/availability` обновляет `available`. |
| WB → Z2M | `TestWbToZ2mCommands` | Команда на `/devices/<id>/controls/<c>/on` транслируется в `<base>/<name>/set` с правильным JSON; оптимистичное значение публикуется на сам контрол сразу. |
| Pending command debounce | `TestPendingCommandDebounce` | В пределах 5с входящий state с расхождением подавляется; после истечения окна — публикуется; подтверждающий state очищает pending. |
| Stats throttling | `TestStatsThrottling` | `Messages received` обновляется не чаще 1 раза в секунду (контролируется через `fake_clock`). |
| События устройств | `TestDeviceEvents` | `device_leave` и `bridge/response/device/remove` удаляют устройство из WB и обновляют `Last left`; `device_renamed` переносит retained-состояние со старого `device_id` на новый. |
| Stale cleanup | `TestStaleDeviceCleanup` | Устройство, пропавшее из нового списка `bridge/devices`, удаляется; пустой `bridge/devices` удаляет все устройства, `Device count` обнуляется. |
| Ghost cleanup | `TestGhostCleanup` | Retained устройства с прошлого запуска (наш `driver`, но не в текущем `bridge/devices`) затираются после первого `bridge/devices`. |
| Reconnect | `TestReconnectFlow` | `republish()` инкрементит `Reconnects`; `set_all_unavailable()` переводит все известные устройства в `available=0`. |

### `tests/integration/test_app_lifecycle.py`

Проверяют [`wb/mqtt_zigbee/app.py`](../wb/mqtt_zigbee/app.py) — класс `WbZigbee2Mqtt`, который держит MQTT-соединение и переводит коллбэки `on_connect`/`on_disconnect` в действия над `Bridge`. Тесты подменяют конструктор `MQTTClient` через `monkeypatch.setattr`, чтобы получить `FakeMqttClient`, и подменяют `signal.signal` на no-op (иначе модификация сигналов мешает pytest). Соединение/разрыв триггерится через `FakeMqttClient.connect(rc=...)` и `disconnect()`.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| Первый connect | `TestFirstConnect` | `connect(rc=0)` вызывает `Bridge.subscribe()` — публикуется `meta` бриджа, проставляются ожидаемые подписки на z2m-топики. |
| Reconnect | `TestReconnect` | `connect(rc=0)` → `disconnect()` → `connect(rc=0)` дёргает `Bridge.republish()`, инкрементит `Reconnects`; после регистрации устройств `disconnect()` помечает все известные устройства `available = "0"`. |
| Connect failure modes | `TestConnectFailureModes` | `connect(rc=5)` (auth) останавливает клиента (`stop()`), не публикует `meta` и не подписывается на топики; `connect(rc=1)` (другие коды) тоже не приводит ни к `subscribe`, ни к `republish`. |
