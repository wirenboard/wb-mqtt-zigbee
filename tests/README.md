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

Проверяют [`wb/mqtt_zigbee/wb_converter/expose_mapper.py`](../wb/mqtt_zigbee/wb_converter/expose_mapper.py) — мост между двумя описаниями одного и того же устройства.

Со стороны Zigbee2MQTT каждое устройство публикует [exposes](https://www.zigbee2mqtt.io/guide/usage/exposes.html) — машинно-читаемый список того, что устройство умеет: датчики, переключатели, диммеры, термостаты и т. д. Дерево, листья — простые типы (`numeric`, `binary`, `enum`, `text`), составные узлы — `light`, `switch`, `climate`, `cover`, `composite` со вложенными `features`.

Со стороны Wiren Board устройство представляется как набор плоских MQTT-контролов с типами и метаданными по [WB MQTT-конвенции](https://github.com/wirenboard/conventions): `temperature`, `rel_humidity`, `switch`, `range`, `value`, `rgb`, `text`, … — каждый со своим title, read-only/read-write, диапазонами, enum-словарями.

`expose_mapper` рекурсивно разворачивает дерево exposes, выбирает подходящий WB-тип для каждого листа и навешивает метаданные. Это чистая функциональная логика без I/O и состояния, покрыта на 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `map_exposes_to_controls` | `TestMapExposesToControls` | Сквозная нумерация `order` начиная с 1;<br> дедупликация по `property` (первое вхождение побеждает);<br> сервисные контролы `available` / `last_seen` добавляются всегда;<br> `device_type` — только при непустом значении;<br> `expose` без `property` пропускается, не ломая порядок. |
| `_flatten_expose` | `TestFlattenExpose` | Листовые фичи проходят как есть;<br> сложные типы (`light`, `switch`, `climate` и др.) раскрываются рекурсивно, в том числе вложенные;<br> `composite` с `property="color"` сворачивается в один RGB-контрол;<br> композитный тип с пустым `features` падает в ветку листа. |
| `_map_leaf_feature` | `TestMapLeafFeature` | Пустой `property` → пустой результат;<br> неизвестный `type` → пустой результат;<br> numeric-свойства маппятся через `NUMERIC_TYPE_MAP` с фоллбеком на `value`;<br> writable numeric `value` с обоими `min` и `max` маппятся в `range`, иначе остаётся `value`;<br> типизированные numeric (`temperature` и т. п.) **не** будут `range` даже с min/max;<br> binary → `switch` + `value_on`/`value_off`;<br> enum → `text` + enum-словарь;<br> text → `text`;<br> `readonly` считается от `access & WRITE`;<br> заголовок формируется из имени `property`. |
| `_map_color_feature` | `TestMapColorFeature` | Writable, если хотя бы один sub-feature writable, иначе readonly;<br> пустой `features` → readonly;<br> тип RGB;<br> title имеют переводы на ru, en. |
| `_make_enum` | `TestMakeEnum` | `["off", "low", "high"]` → `{"off": 0, "low": 1, "high": 2}`;<br> пустой список → `None`. |
| `_make_title` | `TestMakeTitle` | `snake_case` → `Snake case`;<br> единичные слова;<br> параметризованный тест. |
| `_resolve_wb_type` | `TestResolveWbType` | Все ветки (numeric known/unknown, binary, enum, text, unknown → `None`). |

### `tests/unit/test_controls.py` — 55 тестов

Проверяют [`wb/mqtt_zigbee/wb_converter/controls.py`](../wb/mqtt_zigbee/wb_converter/controls.py) — словарь типов WB-контролов и преобразование значений между двумя «диалектами».

На стороне MQTT и контроллера WB значения контролов — это всегда строки в нормированном формате [WB-конвенции](https://github.com/wirenboard/conventions): `"1"`/`"0"` для switch, `"23.5"` для температуры, `"255;128;0"` для RGB и т. п. На стороне z2m те же значения приходят как Python-объекты: `bool`, `int`, `float`, строка из `value_on`/`value_off`, dict `{"hue": …, "saturation": …}` для цвета.

Модуль описывает все используемые WB-типы (`SWITCH`, `RANGE`, `TEMPERATURE`, `RGB`, …), хранит метаданные бридж-устройства Zigbee2MQTT (`Permit join`, `Update devices`, статус, лог-уровень) и содержит конверсию `format_value` / `parse_wb_value` — туда и обратно, с аккуратной обработкой пограничных случаев (None, неверные типы, нулевая насыщенность, roundtrip). Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `_parse_number` | `TestParseNumber` | Целые и дробные числа;<br> `5.0` → `int(5)`;<br> отрицательные значения и ноль;<br> научная нотация (`1e2` → `int(100)`);<br> невалидные строки возвращаются как есть. |
| `_wb_rgb_to_hs_dict` | `TestWbRgbToHsDict` | Базовые цвета (R/G/B);<br> белый и чёрный → нулевая насыщенность;<br> параметризованный тест на невалидные форматы (пусто, неверное число компонент, нечисловые значения) → `{hue: 0, saturation: 0}`. |
| `_hs_dict_to_wb_rgb` | `TestHsDictToWbRgb` | Базовые цвета;<br> нулевая насыщенность → белый;<br> лишние ключи (`x`, `y`) игнорируются;<br> отсутствие `hue`/`saturation` → дефолт `255;255;255`;<br> невалидные типы значений → дефолт;<br> числовые строки принимаются (через `float()`);<br> roundtrip для основных цветов. |
| `ControlMeta.format_value` | `TestControlMetaFormatValue` | `None` → `""`;<br> `bool` → `"1"`/`"0"`;<br> `SWITCH` с `value_on` сравнивает строкой;<br> `RGB` с dict идёт через `_hs_dict_to_wb_rgb`;<br> прочий dict сериализуется в JSON;<br> числа и строки — через `str()`;<br> `bool` имеет приоритет над веткой `SWITCH+value_on`. |
| `ControlMeta.parse_wb_value` | `TestControlMetaParseWbValue` | `SWITCH` без `value_on` → `bool`;<br> `SWITCH` с `value_on` → исходная строка z2m;<br> `RGB` → HS-dict (включая фоллбек на дефолт при ошибке);<br> `TEXT` возвращает строку как есть (даже `"123"`);<br> все числовые типы (`VALUE`, `RANGE`, `TEMPERATURE`, `POWER`, …) идут через `_parse_number`;<br> roundtrip `format → parse` для switch (bool и string режимы). |
| `ControlMeta` defaults | `TestControlMetaDefaults` | Дефолтные значения опциональных полей;<br> `default_factory=dict` для `title` создаёт независимый словарь на каждый инстанс. |
| `BRIDGE_CONTROLS` | `TestBridgeControls` | Все ожидаемые ключи присутствуют;<br> значения `order` уникальны и идут подряд от 1;<br> у каждого контрола есть переводы `en` и `ru`;<br> writable только `Permit join` и `Update devices`;<br> `Permit join` — `switch`, `Update devices` — `pushbutton`. |

### `tests/unit/test_model.py` — 37 тестов

Проверяют [`wb/mqtt_zigbee/z2m/model.py`](../wb/mqtt_zigbee/z2m/model.py) — типизированную модель того, что приходит от Zigbee2MQTT по MQTT.

z2m публикует JSON в свои топики (`bridge/info`, `bridge/devices`, `bridge/event`, …); модуль описывает эти сообщения как dataclass'ы (`BridgeInfo`, `Z2MDevice`, `ExposeFeature`, `DeviceEvent`, …) и константы-перечисления (`BridgeState`, `DeviceAvailability`, `ExposeAccess`, `ExposeType`, `Z2MEventType`, `DeviceEventType`, `BridgeLogLevel`). Парсинг идёт через `from_dict()` — терпимо к отсутствующим/`null`-полям, с рекурсией по вложенным [exposes](https://www.zigbee2mqtt.io/guide/usage/exposes.html).

Тесты проверяют, что dataclass'ы корректно собираются из реальных z2m-словарей, дефолты на месте и `default_factory` не делит контейнеры между инстансами. Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `_str_or_none` | `TestStrOrNone` | `None` остаётся `None`;<br> строка возвращается как есть;<br> числа и `bool` приводятся к строке (`1`, `"True"`, `"False"`);<br> пустая строка не превращается в `None`. |
| `ExposeFeature.is_writable` | `TestExposeFeatureIsWritable` | `True`, если установлен бит `WRITE`;<br> `False` для только `READ`, нулевого `access` и только `GET`. |
| `ExposeFeature.from_dict` | `TestExposeFeatureFromDict` | Полный лист со всеми полями;<br> пустой dict даёт значения по умолчанию;<br> `value_on`/`value_off` пропускаются через `_str_or_none` (включая `bool` → `"True"`/`"False"` и `None` → `None`);<br> `enum` сохраняет `values`;<br> `composite`/`light` рекурсивно парсит `features`, в т.ч. глубоко вложенные. |
| `Z2MDevice.from_dict` | `TestZ2MDeviceFromDict` | Полное устройство с `definition`;<br> пустой dict;<br> `definition: null` (z2m возвращает так для неподдерживаемых устройств) — модель/вендор/exposes пустые;<br> `definition` отсутствует целиком;<br> `definition` без `exposes`. |
| Defaults дата-классов | `TestDataclassDefaults` | `BridgeInfo` принимает обязательные поля;<br> у `DeviceEvent.old_name` дефолт `""`;<br> `default_factory` для `values`/`features`/`exposes` создаёт независимые контейнеры на каждый инстанс. |
| Константы-перечисления | `TestEnumLikeConstants` | Битовые значения `ExposeAccess`;<br> строковые значения `BridgeState`, `DeviceAvailability`, `Z2MEventType`, `DeviceEventType`;<br> все `ExposeType.*` — непустые уникальные строки. |
| `BridgeLogLevel` | `TestBridgeLogLevel` | `RANK` упорядочен `debug < info < warning < error`;<br> покрывает все четыре уровня;<br> строковые значения уровней. |

### `tests/unit/test_config_loader.py` — 22 теста

Проверяют [`wb/mqtt_zigbee/config_loader.py`](../wb/mqtt_zigbee/config_loader.py) — загрузку и валидацию JSON-конфига `wb-mqtt-zigbee.conf`.

Конфиг задаёт минимум: адрес MQTT-брокера, базовый топик zigbee2mqtt, плюс опционально — имя/ID бридж-устройства в WB, минимальный лог-уровень и debounce команд. Загрузчик проверяет наличие обязательных ключей, приводит типы (`command_debounce_sec` → `float`), валидирует `bridge_log_min_level` против известных уровней z2m (lowercase: `debug`/`info`/`warning`/`error`), а на неизвестное значение мягко падает на дефолт с warning'ом в лог.

Все тесты используют фикстуру `tmp_path` и хелпер `write_config()` для генерации временных файлов; походов в файловую систему за пределами `tmp_path` нет. Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| Успешная загрузка | `TestLoadConfigSuccess` | Минимальный конфиг (только обязательные ключи) применяет все дефолты;<br> полный конфиг переопределяет каждый дефолт;<br> `command_debounce_sec`, заданный целым, приводится к `float`;<br> параметризованный тест на все 4 валидных значения `bridge_log_min_level`. |
| Ошибки загрузки | `TestLoadConfigErrors` | Несуществующий файл → `FileNotFoundError`;<br> путь-директория тоже даёт `FileNotFoundError`;<br> невалидный JSON → `ValueError("not valid JSON")`;<br> отсутствие `broker_url` или `zigbee2mqtt_base_topic` → `ValueError("Missing required configuration key")`;<br> нечисловой `command_debounce_sec` → `ValueError` от `float()`. |
| `_validate_log_level` | `TestValidateLogLevel` | Параметризованно для 4 валидных уровней — возвращаются как есть;<br> неизвестный уровень → дефолт + warning в логе (через `caplog`);<br> end-to-end через `load_config` — невалидный уровень в файле тоже падает на дефолт;<br> пустая строка и uppercase (`"ERROR"`) считаются невалидными (z2m уровни — lowercase). |
| Дефолты-константы | `TestDefaults` | Значения `BRIDGE_DEVICE_ID_DEFAULT`, `BRIDGE_DEVICE_NAME_DEFAULT`, `BRIDGE_LOG_MIN_LEVEL_DEFAULT`, `COMMAND_DEBOUNCE_SEC_DEFAULT`. |

### `tests/unit/test_registered_device.py` — 6 тестов

Проверяют [`wb/mqtt_zigbee/registered_device.py`](../wb/mqtt_zigbee/registered_device.py) — внутренний кэш состояния устройства, который бридж держит между MQTT-публикациями и командами от пользователя.

На каждое распознанное Zigbee-устройство хранится `RegisteredDevice`: исходный `Z2MDevice`, словарь его WB-контролов, `device_id` в WB MQTT, флаг получения availability и таблица «висящих» команд `pending_commands`. Каждая команда — `PendingCommand` с уже опубликованным WB-значением и `timestamp` отправки; нужны для debounce и optimistic-обновления состояния (пока z2m не подтвердил команду ответным сообщением).

Это маленькие dataclass'ы без логики; тесты фиксируют дефолты, изоляцию `default_factory` и сохранение полей. Покрытие — 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `PendingCommand` | `TestPendingCommand` | Сохранение полей;<br> сравнение по значению (dataclass-equality). |
| `RegisteredDevice` | `TestRegisteredDevice` | Дефолты `pending_commands={}` и `availability_received=False`;<br> `default_factory` для `pending_commands` создаёт независимый словарь на каждый инстанс;<br> принимает переопределение всех полей;<br> `controls` хранится по ссылке (мутации видны в инстансе). |
