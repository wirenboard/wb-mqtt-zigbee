# Идеи для рефакторинга

Список замечаний, которые всплывают при работе с кодом, но не входят
в текущую задачу.

Формат записи: одна секция `##` на пункт, новые сверху. Шапка из трёх
полей: `Область`, `Тип`, `Дата добавления`. Когда пункт сделан —
просто удалять из файла; история закрытых пунктов смотрится по git
log файла и связанным PR на GitHub.

---

## _str_or_none для value_on/value_off: bool → "True", не "true"
**Область:** `wb/mqtt_zigbee/z2m/model.py` (`_str_or_none`), `wb/mqtt_zigbee/wb_converter/controls.py` (`ControlMeta.format_value`, `parse_wb_value`)
**Тип:** silent breakage risk
**Дата добавления:** 2026-04-30

`_str_or_none` использует `str(value)`, что для bool даёт `"True"`/`"False"`
с большой буквы. Сейчас z2m обычно присылает `value_on`/`value_off`
строками (`"ON"`/`"OFF"`), поэтому проблема не проявляется. Если z2m
начнёт присылать bool-литералы — сравнения в `ControlMeta.format_value`
и `parse_wb_value` молча сломаются (control не переключится, ошибки
не будет).

Решение: явная нормализация в `_str_or_none` —
`str(value).lower() if isinstance(value, bool) else str(value)`,
либо переход на сравнение нормализованных значений в `controls.py`.

## ControlMeta → ControlAdapter
**Область:** `wb/mqtt_zigbee/wb_converter/controls.py`
**Тип:** rename / читаемость
**Дата добавления:** 2026-04-30

Сейчас класс совмещает две роли: описание контрола (тип, title,
read-only, диапазоны, enum) и поведение (`format_value`,
`parse_wb_value` — конверсия z2m ↔ WB MQTT). Суффикс `Meta` намекает
только на первое; вторая роль из имени не считывается, и при чтении
кода приходится лезть в исходник.

Предлагаемое имя: `ControlAdapter` — сохраняет «control» и явно
говорит про адаптацию между двумя системами.

Затронет: `wb_converter/controls.py`, `wb_converter/expose_mapper.py`,
`wb_converter/publisher.py`, `registered_device.py`, тесты
`test_controls.py`, `test_expose_mapper.py`, `test_registered_device.py`.
