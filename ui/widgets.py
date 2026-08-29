"""Declarative config-driven widget builder.

Replaces the inline widget creation code in ``streamlit_app.py`` with a
data-driven approach.  Each widget is defined as a dataclass entry; a
single ``render_sidebar()`` function iterates over the config and renders
all widgets in the correct order with section headings and conditional
visibility.

Widget types
------------
- ``NumberInput`` — ``st.number_input`` with min/max/step
- ``Slider`` — ``st.slider`` with min/max/step
- ``Checkbox`` — ``st.checkbox``
- ``Selectbox`` — ``st.selectbox`` with option list
- ``Radio`` — ``st.radio`` with option list
- ``Custom`` — arbitrary callable for widgets that don't fit the above
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import streamlit as st


# ── Widget entry types ────────────────────────────────────────────────


@dataclass(frozen=True)
class NumberInput:
    label: str
    key: str
    min_value: float = 0.0
    max_value: float | None = None
    step: float = 1.0
    value: float | None = None
    help: str = ""
    disabled: bool = False


@dataclass(frozen=True)
class Slider:
    label: str
    key: str
    min_value: float = 0.0
    max_value: float = 1.0
    step: float = 0.05
    value: float | None = None
    help: str = ""
    disabled: bool = False
    format: str = "%g"


@dataclass(frozen=True)
class Checkbox:
    label: str
    key: str
    value: bool = False
    help: str = ""


@dataclass(frozen=True)
class Selectbox:
    label: str
    key: str
    options: list[Any] = field(default_factory=list)
    index: int = 0
    help: str = ""
    disabled: bool = False
    on_change: Callable[[], Any] | None = None


@dataclass(frozen=True)
class Radio:
    label: str
    key: str
    options: list[Any] = field(default_factory=list)
    index: int = 0
    help: str = ""


@dataclass(frozen=True)
class Custom:
    """Render an arbitrary widget via a callable.

    The callable receives no arguments and should call ``st.*`` directly.
    """
    renderer: Callable[[], Any]


@dataclass(frozen=True)
class SectionHeading:
    """Render an eyebrow section heading."""
    text: str


@dataclass(frozen=True)
class Expander:
    """Wrap subsequent entries in a ``st.expander``."""
    label: str
    expanded: bool = False


@dataclass(frozen=True)
class ConditionalBlock:
    """A block of entries that only renders when ``visible_when()`` is true."""
    visible_when: Callable[[], bool]
    entries: list[Any]


# ── Entry type union ──────────────────────────────────────────────────

WidgetEntry = (
    NumberInput | Slider | Checkbox | Selectbox | Radio |
    Custom | SectionHeading | Expander | ConditionalBlock
)


# ── Renderer ──────────────────────────────────────────────────────────


def _render_entry(entry: WidgetEntry) -> None:
    """Render a single widget entry."""
    if isinstance(entry, NumberInput):
        kwargs: dict[str, Any] = {
            "min_value": entry.min_value,
            "key": entry.key,
            "help": entry.help or None,
        }
        if entry.max_value is not None:
            kwargs["max_value"] = entry.max_value
        if entry.step is not None:
            kwargs["step"] = entry.step
        if entry.value is not None:
            kwargs["value"] = entry.value
        if entry.disabled:
            kwargs["disabled"] = True
        st.number_input(entry.label, **kwargs)

    elif isinstance(entry, Slider):
        kwargs = {
            "min_value": entry.min_value,
            "max_value": entry.max_value,
            "step": entry.step,
            "key": entry.key,
            "format": entry.format,
            "help": entry.help or None,
        }
        if entry.value is not None:
            kwargs["value"] = entry.value
        if entry.disabled:
            kwargs["disabled"] = True
        st.slider(entry.label, **kwargs)

    elif isinstance(entry, Checkbox):
        kwargs = {"key": entry.key}
        if entry.help:
            kwargs["help"] = entry.help
        if entry.value:
            kwargs["value"] = True
        st.checkbox(entry.label, **kwargs)

    elif isinstance(entry, Selectbox):
        kwargs = {"key": entry.key, "index": entry.index}
        if entry.help:
            kwargs["help"] = entry.help
        if entry.disabled:
            kwargs["disabled"] = True
        if entry.on_change is not None:
            kwargs["on_change"] = entry.on_change
        st.selectbox(entry.label, entry.options, **kwargs)

    elif isinstance(entry, Radio):
        kwargs = {"key": entry.key, "index": entry.index}
        if entry.help:
            kwargs["help"] = entry.help
        st.radio(entry.label, entry.options, **kwargs)

    elif isinstance(entry, SectionHeading):
        st.markdown(
            f'<div class="eyebrow">{entry.text}</div>',
            unsafe_allow_html=True,
        )

    elif isinstance(entry, Expander):
        with st.expander(entry.label, expanded=entry.expanded):
            for child in entry.entries:
                _render_entry(child)

    elif isinstance(entry, ConditionalBlock):
        if entry.visible_when():
            for child in entry.entries:
                _render_entry(child)

    elif isinstance(entry, Custom):
        entry.renderer()

    else:
        raise TypeError(f"Unknown widget entry type: {type(entry)}")


def render_entries(entries: list[WidgetEntry]) -> None:
    """Render a list of widget entries in order."""
    for entry in entries:
        _render_entry(entry)
