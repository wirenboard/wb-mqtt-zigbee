# wb-mqtt-zigbee

Сервис-мост между [zigbee2mqtt](https://www.zigbee2mqtt.io/) и [Wiren Board MQTT Conventions](https://github.com/wirenboard/conventions). Автоматически создает виртуальные WB-устройства для всех Zigbee-устройств, обнаруженных zigbee2mqtt.

## Как выглядит

### Устройство моста

Показывает состояние zigbee2mqtt: версию, количество устройств, управление сопряжением, логи и события.

<img src="docs/pics/bridge.png" height="200">

### Zigbee-устройство

Каждое Zigbee-устройство отображается как виртуальное WB-устройство с контролами, соответствующими его возможностям. Контролы генерируются автоматически из `exposes`-схемы zigbee2mqtt.

Для примера возьмем одно из самых распространенных zigbee реле:

<img src="docs/pics/relay_store.jpg" height="200">

Вот так это устройство будет выглядеть в нашем интерфейсе:

<img src="docs/pics/relay_on.png" height="200"> <img src="docs/pics/relay_enum.png" height="200"> 

## Возможности

- Автоматическое обнаружение и регистрация Zigbee-устройств (датчики, реле, лампы, кнопки)
- Двустороннее управление: переключатели, диммеры, цветные лампы (RGB) из WB UI
- Отслеживание доступности устройств (online/offline)
- Поддержка переименования и удаления устройств через zigbee2mqtt

## Документация для разработчиков

- [docs/arc42.md](docs/arc42.md) — архитектура (arc42)
- [docs/v1-analysis.md](docs/v1-analysis.md) — анализ предыдущей версии (JS/wb-rules)
