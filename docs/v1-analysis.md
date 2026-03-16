# Анализ wb-zigbee2mqtt v1

Описание работы старой версии ([репозиторий](https://github.com/wirenboard/wb-zigbee2mqtt)), написанной на JavaScript для движка правил wb-rules.

## Общая схема

```
Zigbee-устройство → координатор → zigbee2mqtt (MQTT) → wb-zigbee2mqtt.js (wb-rules) → виртуальные устройства Wiren Board
```

Единственный файл `wb-zigbee2mqtt.js` устанавливается в `/usr/share/wb-rules-system/rules/` и выполняется движком wb-rules при старте.

## Виртуальное устройство моста

При старте создаётся одно постоянное виртуальное устройство `zigbee2mqtt` с контролами:

| Контрол | Тип | Назначение |
|---|---|---|
| `State` | text | Состояние моста (`online`/`offline`) |
| `Permit join` | switch | Разрешить сопряжение новых устройств |
| `Update devices` | pushbutton | Запросить обновление списка устройств |
| `Version` | text | Версия zigbee2mqtt |
| `Log level` | text | Уровень логирования |
| `Log` | text | Последнее сообщение из лога |

## Подписки на MQTT-топики

### Топики моста

| Топик | Версии z2m | Что делает |
|---|---|---|
| `zigbee2mqtt/bridge/state` | все | Обновляет `State`; при `online` через 5 сек запрашивает список устройств |
| `zigbee2mqtt/bridge/config` | до 1.21 | Читает `log_level` и `version` |
| `zigbee2mqtt/bridge/info` | 1.21+ | Читает `version` и `permit_join` |
| `zigbee2mqtt/bridge/log` | 1.18.x | Обновляет `Log` |
| `zigbee2mqtt/bridge/logging` | 1.21+ | Обновляет `Log` и `Log level` из JSON; игнорирует строки, начинающиеся с `MQTT publish` |
| `zigbee2mqtt/bridge/response/permit_join` | все | Синхронизирует переключатель `Permit join` с реальным состоянием |
| `zigbee2mqtt/bridge/devices` | все | Обнаруживает устройства и создаёт под них виртуальные устройства |

### Команды (публикации)

| Топик | Когда |
|---|---|
| `zigbee2mqtt/bridge/devices/get` | По кнопке `Update devices` или при появлении моста `online` |
| `zigbee2mqtt/bridge/request/permit_join` | При переключении `Permit join` |

## Обнаружение и создание устройств

1. Zigbee-устройство отправляет данные координатору по радиоканалу.
2. Координатор передаёт данные в zigbee2mqtt, который публикует список устройств в `zigbee2mqtt/bridge/devices`.
3. По приходу этого сообщения парсится JSON-массив.
4. Для каждого устройства с `friendly_name != 'Coordinator'`:
   - `/` в `friendly_name` заменяется на `_` (функция `getFriendlyName`).
   - Если виртуального устройства с таким именем ещё нет — создаётся `defineVirtualDevice`.
   - Запускается `initTracker(friendly_name)`.
5. `initTracker` подписывается на `zigbee2mqtt/{friendly_name}`.
   - Когда устройство отправляет новое состояние → координатор → zigbee2mqtt публикует в этот топик.
   - По каждому сообщению парсится JSON с атрибутами устройства.
   - Если контрол с именем атрибута ещё не существует — создаётся через `addControl` с `readonly: true`.
   - Если уже существует — обновляется значение.

## Маппинг типов контролов

Известные атрибуты получают специфичный тип Wiren Board, все остальные — `text`:

```javascript
battery         → 'value'
linkquality     → 'value'
temperature     → 'temperature'
humidity        → 'rel_humidity'
pressure        → 'atmospheric_pressure'
co2             → 'concentration'
voc             → 'value'
illuminance     → 'value'
illuminance_lux → 'value'
noise           → 'sound_level'
occupancy_level → 'value'
power           → 'power'
voltage         → 'voltage'
```

Значения типа `object` (вложенный JSON) сериализуются в строку через `JSON.stringify`.
`null` заменяется на пустую строку.

## Логика Permit join

Поведение различается в зависимости от версии zigbee2mqtt:

**v1.x (majorVersion < 2)**
```
переключатель → publish("…/request/permit_join", true/false)
```

**v2.x+**
- Используется payload `{"time": 254}` (включить) и `{"time": 0}` (выключить).
- Флаг `publish_lock` защищает от петли: когда состояние меняется ответом от брокера, повторная публикация блокируется.
- `permit_join_info` хранит последнее известное состояние из `bridge/info`; команда отправляется только если состояние действительно изменилось.

## Известные ограничения v1

- Все контролы устройств доступны только для чтения — отправить команду на устройство нельзя.
- Список типов контролов захардкожен и не расширяется без правки кода.
- Нет поддержки групп zigbee2mqtt.
- Нет поддержки OTA-обновлений устройств.
- Нет автоматических тестов.
- Устройства, удалённые из zigbee2mqtt, не удаляются из виртуальных устройств WB (до перезапуска wb-rules).
- Язык JS/wb-rules ограничивает возможности тестирования и расширения.
