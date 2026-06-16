import logging
import re
from typing import Optional

from ..z2m.model import ExposeFeature, ExposeProperty, ExposeType
from .controls import ControlMeta, WbControlType

logger = logging.getLogger(__name__)

# Mapping of z2m property names to WB control types (for numeric exposes)
NUMERIC_TYPE_MAP: dict[str, str] = {
    ExposeProperty.TEMPERATURE: WbControlType.TEMPERATURE,
    ExposeProperty.LOCAL_TEMPERATURE: WbControlType.TEMPERATURE,
    ExposeProperty.HUMIDITY: WbControlType.REL_HUMIDITY,
    ExposeProperty.PRESSURE: WbControlType.ATMOSPHERIC_PRESSURE,
    ExposeProperty.CO2: WbControlType.CONCENTRATION,
    ExposeProperty.NOISE: WbControlType.SOUND_LEVEL,
    ExposeProperty.POWER: WbControlType.POWER,
    ExposeProperty.VOLTAGE: WbControlType.VOLTAGE,
    ExposeProperty.CURRENT: WbControlType.CURRENT,
    ExposeProperty.ENERGY: WbControlType.POWER_CONSUMPTION,
    ExposeProperty.ILLUMINANCE: WbControlType.ILLUMINANCE,
    ExposeProperty.ILLUMINANCE_LUX: WbControlType.ILLUMINANCE,
}

# Curated en+ru titles for common control properties, used by _localized_title()
# to give zigbee controls a Russian name in the WB UI (default _make_title() is en-only).
# Keys are z2m property names. Endpoint variants (power_l1, …) are composed by
# _localized_title(), not listed here.
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

# z2m milli-unit → WB base-unit conversion factors, keyed by (WB control type, z2m unit).
# Battery/diagnostic voltage and current are reported in mV/mA; WB voltage/current
# control types display V/A.
_UNIT_SCALE_TO_BASE: dict[tuple[str, str], float] = {
    (WbControlType.VOLTAGE, "mV"): 0.001,
    (WbControlType.CURRENT, "mA"): 0.001,
}

# Phase/endpoint suffix on multi-phase meters & multi-gang devices: power_l1, voltage_a, …
# _localized_title() strips it and appends the upper-cased label to the base title.
PHASE_SUFFIX_RE = re.compile(r"^(.+)_(l\d+|[abc])$")

# Specific/composite expose types that contain nested features
NESTED_TYPES = {
    ExposeType.LIGHT,  # dimmable lights, color lights
    ExposeType.SWITCH,  # on/off switches, smart plugs
    ExposeType.LOCK,  # door locks
    ExposeType.CLIMATE,  # thermostats, AC controllers
    ExposeType.FAN,  # fans, ventilation
    ExposeType.COVER,  # blinds, curtains, shutters
    ExposeType.COMPOSITE,  # generic multi-property exposes
}

# Service controls always added by map_exposes_to_controls regardless of exposes
SERVICE_CONTROLS = {"available", "device_type", "power_source", "last_seen"}

_POWER_SOURCE_LABELS = {
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


def map_exposes_to_controls(
    exposes: list[ExposeFeature], device_type: str = "", power_source: str = ""
) -> dict[str, ControlMeta]:
    """Convert a list of z2m expose features into a flat dict of WB controls.

    Recursively flattens all exposes, deduplicates by property name,
    assigns sequential order, and appends service controls (available, device_type, last_seen).

    Example:

        exposes = [
            ExposeFeature(type="numeric", name="temperature", property="temperature"),
            ExposeFeature(type="numeric", name="humidity", property="humidity"),
        ]
        controls = map_exposes_to_controls(exposes, device_type="Router")
        # {
        #     "temperature":  ControlMeta(type="temperature", order=1, ...),
        #     "humidity":     ControlMeta(type="rel_humidity", order=2, ...),
        #     "available":    ControlMeta(type="switch", order=3, readonly=True, ...),
        #     "device_type":  ControlMeta(type="text", order=4, ...),
        #     "last_seen":    ControlMeta(type="text", order=5, ...),
        # }
    """
    controls: dict[str, ControlMeta] = {}
    order = 1
    for expose in exposes:
        for prop, meta in _flatten_expose(expose):
            if prop not in controls:
                meta.order = order
                controls[prop] = meta
                order += 1
    controls["available"] = ControlMeta(
        type=WbControlType.SWITCH,
        readonly=True,
        order=order,
        title={"en": "Available", "ru": "Доступно"},
    )
    order += 1
    if device_type:
        controls["device_type"] = ControlMeta(
            type=WbControlType.TEXT,
            readonly=True,
            order=order,
            title={"en": "Device Type", "ru": "Тип устройства"},
            enum={
                "Router": {"en": "Router", "ru": "Маршрутизатор"},
                "EndDevice": {"en": "End Device", "ru": "Оконечное устройство"},
                "Coordinator": {"en": "Coordinator", "ru": "Координатор"},
            },
        )
        order += 1
    if power_source:
        controls["power_source"] = ControlMeta(
            type=WbControlType.TEXT,
            readonly=True,
            order=order,
            title={"en": "Power Source", "ru": "Тип питания"},
            enum=_POWER_SOURCE_LABELS,
        )
        order += 1
    controls["last_seen"] = ControlMeta(
        type=WbControlType.TEXT,
        readonly=True,
        order=order,
        title={"en": "Last Seen", "ru": "Последняя активность"},
    )
    return controls


def _flatten_expose(expose: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Recursively flatten an expose feature into (property, ControlMeta) pairs.

    Leaf features are mapped directly. Composite types (light, switch, climate, etc.)
    are unwrapped and their nested features are flattened recursively.

    Example:

        # Leaf expose — returned as-is via _map_leaf_feature
        expose = ExposeFeature(type="numeric", name="temperature", property="temperature")
        _flatten_expose(expose)
        # [("temperature", ControlMeta(type="temperature", ...))]

        # Composite expose — nested features are extracted and flattened
        expose = ExposeFeature(type="light", name="light", property="", features=[
            ExposeFeature(type="binary", name="state", property="state",
                          value_on="ON", value_off="OFF"),
            ExposeFeature(type="numeric", name="brightness", property="brightness"),
        ])
        _flatten_expose(expose)
        # [("state", ControlMeta(type="switch", ...)),
        #  ("brightness", ControlMeta(type="value", ...))]
    """
    if expose.type in NESTED_TYPES and expose.features:
        # Composite "color" expose (color_xy/color_hs) → single RGB control
        if expose.type == ExposeType.COMPOSITE and expose.property == "color":
            return _map_color_feature(expose)
        result = []
        for sub in expose.features:
            result.extend(_flatten_expose(sub))
        return result
    return _map_leaf_feature(expose)


def _map_leaf_feature(feature: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Map a single leaf ExposeFeature to a (property, ControlMeta) pair.

    Example:

        feature = ExposeFeature(type="numeric", name="temperature", property="temperature")
        result = _map_leaf_feature(feature)
        # [("temperature", ControlMeta(type="temperature", readonly=True, title={"en": "Temperature"}))]

        feature = ExposeFeature(type="binary", name="occupancy", property="occupancy",
                                value_on="true", value_off="false")
        result = _map_leaf_feature(feature)
        # [("occupancy", ControlMeta(type="switch", readonly=True, title={"en": "Occupancy"},
        #                            value_on="true", value_off="false"))]
    """
    if not feature.property:
        return []

    wb_type = _resolve_wb_type(feature)
    if wb_type is None:
        return []

    title = _localized_title(feature.property)
    enum = _make_enum(feature) if feature.type == ExposeType.ENUM else None
    # Writable numerics with min/max → range (slider), not value (text input)
    if (
        wb_type == WbControlType.VALUE
        and feature.is_writable
        and feature.value_min is not None
        and feature.value_max is not None
    ):
        wb_type = WbControlType.RANGE

    # z2m reports some diagnostics in milli-units (battery voltage in mV, etc.); the
    # WB voltage/current control types display base SI units, so scale to V / A.
    scale = _UNIT_SCALE_TO_BASE.get((wb_type, feature.unit), 1.0)

    # Typed controls (temperature, voltage, …) carry their unit via the WB type, so
    # only pass z2m's unit through for untyped value/range controls (battery %, etc.).
    units = feature.unit if wb_type in (WbControlType.VALUE, WbControlType.RANGE) else ""

    meta = ControlMeta(
        type=wb_type,
        readonly=not feature.is_writable,
        title=title,
        value_on=feature.value_on,
        value_off=feature.value_off,
        enum=enum,
        min=feature.value_min * scale if feature.value_min is not None else None,
        max=feature.value_max * scale if feature.value_max is not None else None,
        units=units,
        scale=scale,
    )
    return [(feature.property, meta)]


def _map_color_feature(feature: ExposeFeature) -> list[tuple[str, ControlMeta]]:
    """Map a composite color expose (color_xy or color_hs) to a single RGB control.

    z2m exposes color as composite with property "color" and nested x/y or hue/saturation.
    We map it to a single WB "rgb" control. The state dict key is "color",
    and format_value handles HS→RGB conversion.

    Example:

        feature = ExposeFeature(type="composite", name="color_hs", property="color", features=[
            ExposeFeature(type="numeric", name="hue", property=""),
            ExposeFeature(type="numeric", name="saturation", property=""),
        ])
        _map_color_feature(feature)
        # [("color", ControlMeta(type="rgb", readonly=True, title={"en": "Color"}))]
    """
    writable = any(sub.is_writable for sub in feature.features) if feature.features else False
    meta = ControlMeta(
        type=WbControlType.RGB,
        readonly=not writable,
        title={"en": "Color", "ru": "Цвет"},
    )
    return [(feature.property, meta)]


def _make_enum(feature: ExposeFeature) -> Optional[dict]:
    """Build WB enum dict from z2m enum values: {"off": 0, "on": 1, ...}"""
    if not feature.values:
        return None
    return {val: idx for idx, val in enumerate(feature.values)}


def _localized_title(property_name: str) -> dict[str, str]:
    """Build a bilingual {"en", "ru"} title for a z2m property.

    Resolution order:
      1. exact match in PROPERTY_TITLES;
      2. phase-suffixed variant (power_l1, voltage_a, …) — base title + phase label,
         for example "power_l1" → {"en": "Power L1", "ru": "Мощность L1"};
      3. fallback — English-only title mechanically derived from the property name.

    Example:

        _localized_title("temperature")  # {"en": "Temperature", "ru": "Температура"}
        _localized_title("power_l2")      # {"en": "Power L2", "ru": "Мощность L2"}
        _localized_title("some_new_property")  # {"en": "Some New Property"}
    """
    if property_name in PROPERTY_TITLES:
        return dict(PROPERTY_TITLES[property_name])
    phase = PHASE_SUFFIX_RE.match(property_name)
    if phase and phase.group(1) in PROPERTY_TITLES:
        base, label = phase.group(1), phase.group(2).upper()
        return {lang: f"{text} {label}" for lang, text in PROPERTY_TITLES[base].items()}
    return {"en": _make_title(property_name)}


def _make_title(property_name: str) -> str:
    """Convert property name to a Title Case title: 'noise_detect_level' → 'Noise Detect Level'.

    Every word is capitalized, per the WB web-interface style guide (English titles
    capitalize each word). This is the en-only fallback for properties not listed
    in PROPERTY_TITLES, so on-the-fly titles follow the same casing as curated ones.
    """
    return " ".join(word.capitalize() for word in property_name.split("_"))


def _resolve_wb_type(feature: ExposeFeature) -> Optional[str]:
    if feature.type == ExposeType.NUMERIC:
        return NUMERIC_TYPE_MAP.get(feature.property, WbControlType.VALUE)
    if feature.type == ExposeType.BINARY:
        return WbControlType.SWITCH
    if feature.type in (ExposeType.ENUM, ExposeType.TEXT):
        return WbControlType.TEXT
    logger.warning("Unknown expose type '%s' for property '%s'", feature.type, feature.property)
    return None
