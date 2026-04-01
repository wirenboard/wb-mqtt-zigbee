# wb-mqtt-zigbee

Сервис-мост между [zigbee2mqtt](https://www.zigbee2mqtt.io/) и [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions). Автоматически создает виртуальные WB-устройства для всех Zigbee-устройств, обнаруженных zigbee2mqtt.

## Возможности

- Автоматическое обнаружение и регистрация Zigbee-устройств (датчики, реле, лампы, кнопки)
- Двустороннее управление: переключатели, диммеры, цветные лампы (RGB) из WB UI
- Отслеживание доступности устройств (online/offline)
- Поддержка переименования и удаления устройств через zigbee2mqtt

## Как выглядит

### Устройство моста

Показывает состояние zigbee2mqtt: версию, количество устройств, управление сопряжением, логи и события.

<img src="docs/pics/bridge.png" height="300">

### Zigbee-устройство

Каждое Zigbee-устройство отображается как виртуальное WB-устройство с контролами, соответствующими его возможностям. Контролы генерируются автоматически из `exposes`-схемы zigbee2mqtt.

Вот такое zigbee реле:

<img src="docs/pics/relay_store.jpg" height="200">

так будет выглядеть в нашем интерфейсе:

<img src="docs/pics/relay_on.png" height="200"> <img src="docs/pics/relay_enum.png" height="200"> 

## Как это работает

zigbee2mqtt подключается к Zigbee-координатору, обнаруживает устройства и публикует всю информацию в MQTT-брокер. Пространство топиков настраивается в конфиге zigbee2mqtt (`/mnt/data/root/zigbee2mqtt/data/configuration.yaml`, параметр `base_topic`), по умолчанию — `zigbee2mqtt/`:

```
zigbee2mqtt/bridge/state       → "online"
zigbee2mqtt/bridge/info        → {"version": "2.1.0", "permit_join": false, ...}
zigbee2mqtt/bridge/devices     → [{...}, {...}, ...]
zigbee2mqtt/bridge/logging     → {"level": "info", "message": "..."}
zigbee2mqtt/bridge/event       → {"type": "device_joined", "data": {...}}
zigbee2mqtt/living_room_sensor → {"temperature": 23.5, "humidity": 45}
```

Wiren Board работает с другим форматом — [WB MQTT Conventions](https://github.com/wirenboard/conventions), где каждое устройство представлено набором топиков вида `/devices/{id}/controls/{name}`.

**wb-mqtt-zigbee** связывает эти два мира:

1. **Подписывается** на топики `zigbee2mqtt/` и получает состояние моста, список устройств, логи и события
2. **Создает виртуальные WB-устройства** в `/devices/` — публикует метаданные (`/meta`) и значения контролов по WB MQTT Conventions
3. **Транслирует команды обратно** — когда пользователь нажимает кнопку или переключает переключатель в WB UI, сервис получает команду из `/devices/.../on` и публикует соответствующий запрос в `zigbee2mqtt/bridge/request/...`

На схеме ниже показано движение данных через mqtt брокер (mosquitto): слева — пространство топиков zigbee2mqtt, справа — пространство контроллера WirenBoard. Стрелки двунаправленные: состояния устройств идут слева направо, команды — справа налево.

```
Zigbee-устройства
       │ Zigbee
       ▼
   zigbee2mqtt ──── MQTT ────► wb-mqtt-zigbee ──── MQTT ────► Wiren Board UI
              zigbee2mqtt/*                     /devices/*
              ◄──── MQTT ────                   ◄──── MQTT ────
              запросы (set/get)                 команды (/on)
```

> **На что обратить внимание:** оба пространства топиков живут в одном MQTT-брокере (mosquitto).
> Список устройств (`bridge/devices`) публикуется как *retained* один раз при старте zigbee2mqtt.


## Документация для разработчиков

- [docs/arc42.md](docs/arc42.md) — архитектура (arc42)
- [docs/v1-analysis.md](docs/v1-analysis.md) — анализ предыдущей версии (JS/wb-rules)
