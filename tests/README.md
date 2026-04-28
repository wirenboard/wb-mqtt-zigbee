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
├── conftest.py                 # общие фикстуры (пока пустой)
├── README.md                   # этот файл
├── unit/                       # unit-тесты (без I/O)
│   ├── __init__.py
│   ├── test_config_loader.py
│   ├── test_controls.py
│   ├── test_expose_mapper.py
│   ├── test_model.py
│   └── test_registered_device.py
└── integration/                # интеграционные тесты (требуют брокера/моков)
    └── __init__.py
```

Отдельного pytest-конфига в проекте нет: `tests/__init__.py` и `tests/unit/__init__.py` подсказывают pytest корень, а пакет `wb.mqtt_zigbee` импортируется после `pip install -e .`. Единственная зависимость для базового прогона — `pytest` (закреплена в `dev-requirements.txt`).


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

Coverage снимается через [`pytest-cov`](https://pytest-cov.readthedocs.io/) (обёртка над `coverage.py`). Зависимость закреплена в `dev-requirements.txt`; на Debian/Ubuntu также доступна из apt:

```bash
sudo apt install python3-pytest-cov
```

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

На текущем этапе разработки тестов:

```
Module                                          Stmts  Miss  Cover
------------------------------------------------------------------
wb/mqtt_zigbee/__main__.py                          3     3     0%
wb/mqtt_zigbee/app.py                              57    57     0%
wb/mqtt_zigbee/bridge.py                          268   268     0%
wb/mqtt_zigbee/config_loader.py                    37     0   100%
wb/mqtt_zigbee/main.py                             21    21     0%
wb/mqtt_zigbee/registered_device.py                14     0   100%
wb/mqtt_zigbee/wb_converter/controls.py           106     0   100%
wb/mqtt_zigbee/wb_converter/expose_mapper.py       64     0   100%
wb/mqtt_zigbee/wb_converter/publisher.py          147   147     0%
wb/mqtt_zigbee/z2m/client.py                      146   146     0%
wb/mqtt_zigbee/z2m/model.py                       105     0   100%
------------------------------------------------------------------
TOTAL                                             968   642    34%
```

Вся «чистая» (без I/O) логика покрыта на 100%. Оставшиеся 642 непокрытых строки — это код, тесно завязанный на MQTT-брокер и asyncio-цикл.

Модули, которым unit-тестов недостаточно (нужен broker или моки — это задача для `tests/integration/`):

- `wb/mqtt_zigbee/z2m/client.py` — MQTT-коллбэки, требует брокера или мока.
- `wb/mqtt_zigbee/bridge.py` — оркестрация состояний между z2m и WB, лучше тестировать end-to-end.
- `wb/mqtt_zigbee/wb_converter/publisher.py` — публикует retained MQTT-топики, завязан на брокер.


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

Раздел растёт по мере появления новых тестов. Содержание идёт по тест-файлам.

### `tests/unit/test_expose_mapper.py` — 42 теста

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

### `tests/unit/test_controls.py` — 55 тестов

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

### `tests/unit/test_model.py` — 37 тестов

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

### `tests/unit/test_config_loader.py` — 22 теста

Проверяют [`wb/mqtt_zigbee/config_loader.py`](../wb/mqtt_zigbee/config_loader.py) — загрузка и валидация JSON-конфига `wb-mqtt-zigbee.conf`. Все тесты используют фикстуру `tmp_path` и хелпер `write_config()` для генерации временных файлов; походов в файловую систему за пределами `tmp_path` нет. Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| Успешная загрузка | `TestLoadConfigSuccess` | Минимальный конфиг (только обязательные ключи) применяет все дефолты; полный конфиг переопределяет каждый дефолт; `command_debounce_sec`, заданный целым, приводится к `float`; параметризованный тест на все 4 валидных значения `bridge_log_min_level`. |
| Ошибки загрузки | `TestLoadConfigErrors` | Несуществующий файл → `FileNotFoundError`; путь-директория тоже даёт `FileNotFoundError`; невалидный JSON → `ValueError("not valid JSON")`; отсутствие `broker_url` или `zigbee2mqtt_base_topic` → `ValueError("Missing required configuration key")`; нечисловой `command_debounce_sec` → `ValueError` от `float()`. |
| `_validate_log_level` | `TestValidateLogLevel` | Параметризованно для 4 валидных уровней — возвращаются как есть; неизвестный уровень → дефолт + warning в логе (через `caplog`); end-to-end через `load_config` — невалидный уровень в файле тоже падает на дефолт; пустая строка и uppercase (`"ERROR"`) считаются невалидными (z2m уровни — lowercase). |
| Дефолты-константы | `TestDefaults` | Значения `BRIDGE_DEVICE_ID_DEFAULT`, `BRIDGE_DEVICE_NAME_DEFAULT`, `BRIDGE_LOG_MIN_LEVEL_DEFAULT`, `COMMAND_DEBOUNCE_SEC_DEFAULT`. |

### `tests/unit/test_registered_device.py` — 6 тестов

Проверяют [`wb/mqtt_zigbee/registered_device.py`](../wb/mqtt_zigbee/registered_device.py) — дата-классы `PendingCommand` и `RegisteredDevice` (внутренний кэш состояния устройства между MQTT-публикациями и командами). Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `PendingCommand` | `TestPendingCommand` | Сохранение полей; сравнение по значению (dataclass-equality). |
| `RegisteredDevice` | `TestRegisteredDevice` | Дефолты `pending_commands={}` и `availability_received=False`; `default_factory` для `pending_commands` создаёт независимый словарь на каждый инстанс; принимает переопределение всех полей; `controls` хранится по ссылке (мутации видны в инстансе). |
