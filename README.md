# wb-zigbee2mqtt-v2

Сервис-мост между [zigbee2mqtt](https://www.zigbee2mqtt.io/) и [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions).

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

**wb-zigbee2mqtt-v2** связывает эти два мира:

1. **Подписывается** на топики `zigbee2mqtt/` и получает состояние моста, список устройств, логи и события
2. **Создает виртуальные WB-устройства** в `/devices/` — публикует метаданные (`/meta`) и значения контролов по WB MQTT Conventions
3. **Транслирует команды обратно** — когда пользователь нажимает кнопку или переключает переключатель в WB UI, сервис получает команду из `/devices/.../on` и публикует соответствующий запрос в `zigbee2mqtt/bridge/request/...`

```
Zigbee-устройства
       │ Zigbee
       ▼
  zigbee2mqtt ──── MQTT ────► wb-zigbee2mqtt-v2 ──── MQTT ────► Wiren Board UI
              zigbee2mqtt/*                     /devices/*
              ◄──── MQTT ────                   ◄──── MQTT ────
              запросы (set/get)                 команды (/on)
```

На данный момент реализовано виртуальное устройство моста (`zigbee2mqtt`) с контролами: состояние, версия, управление сопряжением, счетчик устройств, события подключения/отключения/удаления, логи с фильтрацией по уровню.

## Документация

- [docs/arc42.md](docs/arc42.md) — архитектура (arc42)
- [docs/development-plan.md](docs/development-plan.md) — план разработки по этапам
- [docs/v1-analysis.md](docs/v1-analysis.md) — анализ предыдущей версии (JS/wb-rules)
