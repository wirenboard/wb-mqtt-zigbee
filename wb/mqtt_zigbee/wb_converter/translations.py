"""en+ru labels published in WB control metadata."""

# Curated en+ru titles for common control properties, keyed by z2m property name.
# Endpoint variants (power_l1, switch_type_1) are composed from the base entry by
# expose_mapper, so they are not listed here.
PROPERTY_TITLES: dict[str, dict[str, str]] = {
    # --- Environment & air-quality sensors ---
    "temperature": {"en": "Temperature", "ru": "Температура"},
    "device_temperature": {"en": "Device Temperature", "ru": "Температура устройства"},
    "local_temperature": {"en": "Local Temperature", "ru": "Текущая температура"},
    "humidity": {"en": "Humidity", "ru": "Влажность"},
    "soil_moisture": {"en": "Soil Moisture", "ru": "Влажность почвы"},
    "pressure": {"en": "Pressure", "ru": "Давление"},
    "co2": {"en": "CO2", "ru": "CO2"},
    "voc": {"en": "VOC", "ru": "VOC"},
    "tvoc": {"en": "TVOC", "ru": "TVOC"},
    "formaldehyde": {"en": "Formaldehyde", "ru": "Формальдегид"},
    "pm25": {"en": "PM2.5", "ru": "PM2.5"},
    "pm10": {"en": "PM10", "ru": "PM10"},
    "noise": {"en": "Noise", "ru": "Шум"},
    "noise_detected": {"en": "Noise Detected", "ru": "Обнаружен шум"},
    "noise_detect_level": {"en": "Noise Detection Level", "ru": "Порог обнаружения шума"},
    "noise_timeout": {"en": "Noise Timeout", "ru": "Таймаут шума"},
    "illuminance": {"en": "Illuminance", "ru": "Освещенность"},
    "illuminance_lux": {"en": "Illuminance", "ru": "Освещенность"},
    "uv_index": {"en": "UV Index", "ru": "UV-индекс"},
    "co2_autocalibration": {"en": "CO2 Auto-Calibration", "ru": "Автокалибровка CO2"},
    "co2_manual_calibration": {"en": "CO2 Manual Calibration", "ru": "Ручная калибровка CO2"},
    "th_heater": {"en": "T/H Heater", "ru": "Нагрев датчика T/H"},
    # --- Electrical metering ---
    "power": {"en": "Power", "ru": "Мощность"},
    "power_factor": {"en": "Power Factor", "ru": "Коэффициент мощности"},
    "power_reactive": {"en": "Reactive Power", "ru": "Реактивная мощность"},
    "power_apparent": {"en": "Apparent Power", "ru": "Полная мощность"},
    "voltage": {"en": "Voltage", "ru": "Напряжение"},
    "current": {"en": "Current", "ru": "Ток"},
    "energy": {"en": "Energy", "ru": "Энергия"},
    "produced_energy": {"en": "Produced Energy", "ru": "Выработанная энергия"},
    "frequency": {"en": "Frequency", "ru": "Частота"},
    "ac_frequency": {"en": "AC Frequency", "ru": "Частота сети"},
    # --- Battery & connectivity ---
    "battery": {"en": "Battery", "ru": "Заряд батареи"},
    "battery_low": {"en": "Battery Low", "ru": "Низкий заряд батареи"},
    "battery_state": {"en": "Battery State", "ru": "Состояние батареи"},
    "battery_voltage": {"en": "Battery Voltage", "ru": "Напряжение батареи"},
    "linkquality": {"en": "Link Quality", "ru": "Качество связи"},
    # --- Binary sensors & security ---
    "occupancy": {"en": "Occupancy", "ru": "Присутствие"},
    "presence": {"en": "Presence", "ru": "Присутствие"},
    "contact": {"en": "Contact", "ru": "Контакт"},
    "water_leak": {"en": "Water Leak", "ru": "Протечка воды"},
    "smoke": {"en": "Smoke", "ru": "Дым"},
    "gas": {"en": "Gas", "ru": "Газ"},
    "carbon_monoxide": {"en": "Carbon Monoxide", "ru": "Угарный газ"},
    "vibration": {"en": "Vibration", "ru": "Вибрация"},
    "tamper": {"en": "Tamper", "ru": "Вскрытие корпуса"},
    "moving": {"en": "Moving", "ru": "Движение"},
    "motion": {"en": "Motion", "ru": "Движение"},
    "sos": {"en": "SOS", "ru": "Тревога SOS"},
    "alarm": {"en": "Alarm", "ru": "Тревога"},
    # --- Lights ---
    "state": {"en": "State", "ru": "Состояние"},
    "brightness": {"en": "Brightness", "ru": "Яркость"},
    "color_temp": {"en": "Color Temperature", "ru": "Цветовая температура"},
    "color_temp_startup": {"en": "Startup Color Temperature", "ru": "Цветовая температура при включении"},
    "color": {"en": "Color", "ru": "Цвет"},
    "effect": {"en": "Effect", "ru": "Эффект"},
    "color_mode": {"en": "Color Mode", "ru": "Цветовой режим"},
    "min_brightness": {"en": "Minimum Brightness", "ru": "Минимальная яркость"},
    "max_brightness": {"en": "Maximum Brightness", "ru": "Максимальная яркость"},
    "color_power_on_behavior": {"en": "Color Power-On Behavior", "ru": "Поведение цвета при включении"},
    "do_not_disturb": {"en": "Do Not Disturb", "ru": "Не беспокоить"},
    # --- Switches / plugs ---
    "power_on_behavior": {"en": "Power-On Behavior", "ru": "Поведение при включении"},
    "child_lock": {"en": "Child Lock", "ru": "Блокировка от детей"},
    "button_lock": {"en": "Button Lock", "ru": "Блокировка кнопок"},
    "indicator_mode": {"en": "Indicator Mode", "ru": "Режим индикатора"},
    "backlight_mode": {"en": "Backlight Mode", "ru": "Режим подсветки"},
    "led_disabled_night": {"en": "Disable LED At Night", "ru": "Отключать LED ночью"},
    "switch_type": {"en": "Switch Type", "ru": "Тип выключателя"},
    # Neutral on purpose: converters use it both as a supply level (full/low/…) and as
    # a supply indicator (battery_*/usb). Must not repeat power_source's «Тип питания».
    "power_type": {"en": "Power Type", "ru": "Питание"},
    "operation_mode": {"en": "Operation Mode", "ru": "Режим работы"},
    # --- Climate / thermostat ---
    "system_mode": {"en": "System Mode", "ru": "Режим работы"},
    "running_state": {"en": "Running State", "ru": "Текущий режим"},
    "running_mode": {"en": "Running Mode", "ru": "Активный режим"},
    "preset": {"en": "Preset", "ru": "Пресет"},
    "fan_mode": {"en": "Fan Mode", "ru": "Режим вентилятора"},
    "current_heating_setpoint": {"en": "Heating Setpoint", "ru": "Заданная температура"},
    "occupied_heating_setpoint": {"en": "Heating Setpoint", "ru": "Заданная температура нагрева"},
    "occupied_cooling_setpoint": {"en": "Cooling Setpoint", "ru": "Заданная температура охлаждения"},
    "local_temperature_calibration": {"en": "Temperature Calibration", "ru": "Калибровка температуры"},
    "valve_position": {"en": "Valve Position", "ru": "Положение клапана"},
    "pi_heating_demand": {"en": "Heating Demand", "ru": "Запрос на нагрев"},
    "window_detection": {"en": "Open Window Detection", "ru": "Обнаружение открытого окна"},
    "window_open": {"en": "Window Open", "ru": "Окно открыто"},
    "boost": {"en": "Boost", "ru": "Турбо"},
    "boost_time": {"en": "Boost Time", "ru": "Время турбо-режима"},
    "comfort_temperature": {"en": "Comfort Temperature", "ru": "Комфортная температура"},
    "eco_temperature": {"en": "Eco Temperature", "ru": "Эко-температура"},
    "away_mode": {"en": "Away Mode", "ru": "Режим отсутствия"},
    "eco_mode": {"en": "Eco Mode", "ru": "Эко-режим"},
    "heating": {"en": "Heating", "ru": "Нагрев"},
    "min_temperature": {"en": "Minimum Temperature", "ru": "Минимальная температура"},
    "max_temperature": {"en": "Maximum Temperature", "ru": "Максимальная температура"},
    # --- Covers & locks ---
    "position": {"en": "Position", "ru": "Положение"},
    "tilt": {"en": "Tilt", "ru": "Наклон"},
    "motor_state": {"en": "Motor State", "ru": "Состояние мотора"},
    "motor_direction": {"en": "Motor Direction", "ru": "Направление мотора"},
    "calibration": {"en": "Calibration", "ru": "Калибровка"},
    "calibration_time": {"en": "Calibration Time", "ru": "Время калибровки"},
    "lock_state": {"en": "Lock State", "ru": "Состояние замка"},
    "auto_lock": {"en": "Auto Lock", "ru": "Автоблокировка"},
    "sound_volume": {"en": "Sound Volume", "ru": "Громкость звука"},
    # --- Controls & actions ---
    "action": {"en": "Action", "ru": "Действие"},
    "moving_state": {"en": "Moving State", "ru": "Состояние движения"},
    # --- Sensitivity / timing / calibration config ---
    "sensitivity": {"en": "Sensitivity", "ru": "Чувствительность"},
    "motion_sensitivity": {"en": "Motion Sensitivity", "ru": "Чувствительность к движению"},
    "presence_sensitivity": {"en": "Presence Sensitivity", "ru": "Чувствительность к присутствию"},
    "occupancy_sensitivity": {"en": "Occupancy Sensitivity", "ru": "Чувствительность к присутствию"},
    "occupancy_level": {"en": "Occupancy Level", "ru": "Уровень присутствия"},
    "detection_distance": {"en": "Detection Distance", "ru": "Дистанция обнаружения"},
    "detection_distance_max": {
        "en": "Maximum Detection Distance",
        "ru": "Максимальная дистанция обнаружения",
    },
    "detection_distance_min": {"en": "Minimum Detection Distance", "ru": "Минимальная дистанция обнаружения"},
    "target_distance": {"en": "Target Distance", "ru": "Дистанция до цели"},
    "occupancy_timeout": {"en": "Occupancy Timeout", "ru": "Таймаут присутствия"},
    "detection_interval": {"en": "Detection Interval", "ru": "Интервал обнаружения"},
    "fading_time": {"en": "Fading Time", "ru": "Время затухания"},
    "keep_time": {"en": "Keep Time", "ru": "Время удержания"},
    "duration": {"en": "Duration", "ru": "Длительность"},
    "max_duration": {"en": "Maximum Duration", "ru": "Максимальная длительность"},
    "temperature_calibration": {"en": "Temperature Calibration", "ru": "Калибровка температуры"},
    "temperature_offset": {"en": "Temperature Offset", "ru": "Смещение температуры"},
    "humidity_calibration": {"en": "Humidity Calibration", "ru": "Калибровка влажности"},
    "illuminance_calibration": {"en": "Illuminance Calibration", "ru": "Калибровка освещенности"},
    "pressure_calibration": {"en": "Pressure Calibration", "ru": "Калибровка давления"},
    "temperature_unit": {"en": "Temperature Unit", "ru": "Единица температуры"},
    # --- Siren / misc ---
    "melody": {"en": "Melody", "ru": "Мелодия"},
    "volume": {"en": "Volume", "ru": "Громкость"},
    "strobe": {"en": "Strobe", "ru": "Стробоскоп"},
    # --- LEDs / indicators / on-device diagnostics ---
    "indicator": {"en": "Indicator", "ru": "Индикатор"},
    "activity_led_indicator": {"en": "Activity LED Indicator", "ru": "LED-индикатор активности"},
    "uart_connection": {"en": "UART Connection", "ru": "Связь по UART"},
    "uart_baud_rate": {"en": "UART Baud Rate", "ru": "Скорость UART"},
}

# en+ru labels for z2m enum VALUES, keyed by property then by value.
# Keyed by property, not globally by value: the Russian form differs per property
# ("low" is «Низкое» for power_type, «Низкая» for sensitivity). A miss falls back to
# English. Open-ended enums (action, effect, melody) are left uncurated on purpose.

ENUM_VALUE_TITLES: dict[str, dict[str, dict[str, str]]] = {
    "switch_type": {
        "rocker": {"en": "Rocker", "ru": "Клавишный"},
        "button": {"en": "Button", "ru": "Кнопочный"},
        "decoupled": {"en": "Decoupled", "ru": "Отвязан от реле"},
    },
    # Neuter forms, agreeing with the «Питание» title.
    "power_type": {
        "full": {"en": "Full", "ru": "Полное"},
        "low": {"en": "Low", "ru": "Низкое"},
        "medium": {"en": "Medium", "ru": "Среднее"},
        "high": {"en": "High", "ru": "Высокое"},
    },
    "power_on_behavior": {
        "off": {"en": "Off", "ru": "Выключено"},
        "on": {"en": "On", "ru": "Включено"},
        "toggle": {"en": "Toggle", "ru": "Инвертировать"},
        "previous": {"en": "Previous", "ru": "Восстановить предыдущее"},
    },
    # Do not reuse these labels for color_power_on_behavior: despite the similar name,
    # z2m gives it a different value set (initial/previous/customized).
}

# Same shape as ENUM_VALUE_TITLES, but for a service control, not an enum expose.
POWER_SOURCE_LABELS: dict[str, dict[str, str]] = {
    "Battery": {"en": "Battery", "ru": "Батарея"},
    "Mains (single phase)": {"en": "Mains (single phase)", "ru": "Сеть 220В"},
    "Mains (3 phase)": {"en": "Mains (3 phase)", "ru": "Сеть 380В"},
    "DC Source": {"en": "DC Source", "ru": "Внешний DC"},
    "Emergency mains constantly powered": {
        "en": "Emergency mains constantly powered",
        "ru": "Аварийная сеть (постоянное питание)",
    },
    "Emergency mains and transfer switch": {
        "en": "Emergency mains and transfer switch",
        "ru": "Аварийная сеть с АВР",
    },
    "Unknown": {"en": "Unknown", "ru": "Неизвестно"},
}
