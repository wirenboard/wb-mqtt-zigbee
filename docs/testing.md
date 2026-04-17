# Тестирование

Документ описывает автоматизированный тестовый набор `wb-mqtt-zigbee`: как его запускать, что покрыто и как снимать coverage.

## Структура

```
tests/
├── unit/                       # pytest unit-тесты (быстрые, без I/O)
│   └── wb_converter/
│       └── test_expose_mapper.py
├── integration/                # зарезервировано под будущие pytest integration-тесты
└── scripts/                    # ручные shell-скрипты для проверок на железе (не pytest)
```

Конфигурация — в корне репозитория, [`pytest.ini`](../pytest.ini):

```ini
[pytest]
minversion = 7.0
testpaths = tests/unit tests/integration
pythonpath = .
```

- `testpaths` — pytest собирает тесты только из этих каталогов; `tests/scripts/` исключён.
- `pythonpath = .` — добавляет корень репозитория в `sys.path`, чтобы тесты могли делать `import wb.mqtt_zigbee` без установки пакета.

Единственная зависимость для базового прогона — `pytest` ≥ 7.0.

## Запуск

Из корня репозитория:

```bash
# Весь набор
pytest

# Только unit-тесты
pytest tests/unit

# Конкретный файл, с подробным выводом
pytest tests/unit/wb_converter/test_expose_mapper.py -v

# Фильтр по имени теста/класса (подстрока)
pytest -k "rgb"
pytest -k "TestFlattenExpose"

# Остановиться на первой ошибке, показать локальные переменные
pytest -x --showlocals
```

## Что покрыто

### `tests/unit/wb_converter/test_expose_mapper.py` — 42 теста

Проверяют [`wb/mqtt_zigbee/wb_converter/expose_mapper.py`](../wb/mqtt_zigbee/wb_converter/expose_mapper.py) — модуль, конвертирующий `exposes`-схему zigbee2mqtt в словарь метаданных WB MQTT-контролов. Это чистая функциональная логика (без I/O и состояния), и она покрыта на 100%.

| Цель | Класс тестов | Что проверяется |
|---|---|---|
| `map_exposes_to_controls` | `TestMapExposesToControls` | Сквозная нумерация `order` начиная с 1; дедупликация по `property` (первое вхождение побеждает); сервисные контролы `available` / `last_seen` добавляются всегда; `device_type` — только при непустом значении; экспоуз без `property` пропускается, не ломая порядок. |
| `_flatten_expose` | `TestFlattenExpose` | Листовые фичи проходят как есть; композитные типы (`light`, `switch`, `climate` и др.) раскрываются рекурсивно, в том числе вложенные композиты; `composite` с `property="color"` сворачивается в один RGB-контрол; композитный тип с пустым `features` падает в ветку листа. |
| `_map_leaf_feature` | `TestMapLeafFeature` | Пустой `property` → пустой результат; неизвестный `type` → пустой результат; numeric-свойства маппятся через `NUMERIC_TYPE_MAP` с фоллбеком на `value`; writable numeric `value` с обоими `min` и `max` повышается до `range`, иначе остаётся `value`; типизированные numeric (`temperature` и т. п.) **не** повышаются до `range` даже с min/max; binary → `switch` + `value_on`/`value_off`; enum → `text` + enum-словарь; text → `text`; `readonly` считается от `access & WRITE`; заголовок формируется из имени `property`. |
| `_map_color_feature` | `TestMapColorFeature` | Writable, если хотя бы один sub-feature writable, иначе readonly; пустой `features` → readonly; тип RGB; двуязычный title. |
| `_make_enum` | `TestMakeEnum` | `["off", "low", "high"]` → `{"off": 0, "low": 1, "high": 2}`; пустой список → `None`. |
| `_make_title` | `TestMakeTitle` | `snake_case` → `Snake case`; единичные слова; параметризованный тест. |
| `_resolve_wb_type` | `TestResolveWbType` | Все ветки (numeric known/unknown, binary, enum, text, unknown → `None`). |

### Фабрика `make_expose()`

Все тесты создают `ExposeFeature` через фабрику в начале файла. По умолчанию возвращает читаемый numeric-лист; каждый тест переопределяет только те поля, которые важны именно ему:

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

Константы `READABLE` / `WRITABLE` оборачивают битмаску `ExposeAccess` (1 / 3) — чтобы в тестах читалось назначение, а не магические числа.

## Coverage

Coverage снимается через [`pytest-cov`](https://pytest-cov.readthedocs.io/) (обёртка над `coverage.py`). На Debian/Ubuntu ставится из apt:

```bash
sudo apt install python3-pytest-cov
```

Coverage **не** прописан в `pytest.ini` — чистый `pytest` остаётся быстрым и без дополнительных зависимостей. Запускается явно, когда нужен.

### Три рецепта

В зависимости от того, что именно хочется увидеть:

**1. Общая картина по всему пакету.** Основной режим — показывает, какие модули полностью не покрыты, а какие «подхвачены» случайно через зависимости.

```bash
pytest --cov=wb.mqtt_zigbee --cov-report=term-missing
```

**2. Один подпакет.** Когда активно работаешь в одной области и не нужен шум от нулей из соседних модулей.

```bash
pytest --cov=wb.mqtt_zigbee.wb_converter --cov-report=term-missing
```

**3. Один модуль (+ его тест-файл).** Узкий фокус — закрыты ли все ветки именно этого файла.

```bash
pytest --cov=wb.mqtt_zigbee.wb_converter.expose_mapper \
       tests/unit/wb_converter/test_expose_mapper.py \
       --cov-report=term-missing
```

### Форматы отчёта

- `term-missing` (в примерах выше) — процент + номера непокрытых строк прямо в терминале. Удобно для итеративной работы: видно, куда нести следующий тест.
- `html` — кликабельное дерево в `htmlcov/`, полезно при разрастании проекта:
  ```bash
  pytest --cov=wb.mqtt_zigbee --cov-report=html
  xdg-open htmlcov/index.html
  ```
- `term` (без `missing`) — только проценты, компактнее, но теряется самое полезное.

### Текущее состояние

На момент первой поставки тестов:

```
Module                                       Stmts  Miss  Cover
-------------------------------------------------------------
wb/mqtt_zigbee/wb_converter/expose_mapper.py    64     0   100%
wb/mqtt_zigbee/z2m/model.py                    105     6    94%
wb/mqtt_zigbee/wb_converter/controls.py        106    46    57%
wb/mqtt_zigbee/__main__.py                       3     3     0%
wb/mqtt_zigbee/app.py                           57    57     0%
wb/mqtt_zigbee/bridge.py                       268   268     0%
wb/mqtt_zigbee/config_loader.py                 37    37     0%
wb/mqtt_zigbee/main.py                          21    21     0%
wb/mqtt_zigbee/registered_device.py             14    14     0%
wb/mqtt_zigbee/wb_converter/publisher.py       147   147     0%
wb/mqtt_zigbee/z2m/client.py                   146   146     0%
-------------------------------------------------------------
TOTAL                                          968   745    23%
```

`controls.py` (57%) и `z2m/model.py` (94%) попали в покрытие «бесплатно» — их конструкторы и дата-классы вызываются из тестов на `expose_mapper`. Целенаправленные тесты на них дадут ещё и покрытие методов (`format_value`/`parse_wb_value`, HS↔RGB, `from_dict` и т. д.).

Следующие кандидаты (чистая логика, легко покрыть unit-тестами):

- `wb/mqtt_zigbee/wb_converter/controls.py` — `ControlMeta.format_value` / `parse_wb_value`, конверсия HS↔RGB через `colorsys`, парсинг чисел.
- `wb/mqtt_zigbee/config_loader.py` — загрузка JSON, валидация ключей, дефолты.
- `wb/mqtt_zigbee/z2m/model.py` — `from_dict` для `ExposeFeature`, `Z2MDevice`, `DeviceEvent` (дотянуть с 94% до 100%).

Модули, которым unit-тестов недостаточно (нужен broker или моки — это задача для `tests/integration/`):

- `wb/mqtt_zigbee/z2m/client.py` — MQTT-коллбэки, требует брокера или мока.
- `wb/mqtt_zigbee/bridge.py` — оркестрация состояний между z2m и WB, лучше тестировать end-to-end.
- `wb/mqtt_zigbee/wb_converter/publisher.py` — публикует retained MQTT-топики, завязан на брокер.
