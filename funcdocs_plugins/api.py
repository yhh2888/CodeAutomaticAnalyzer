from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtWidgets import QWidget


RefactorSet = list[dict[str, list[list[str]]]]


@dataclass(frozen=True)
class FunctionContext:
    file_path: str
    function_name: str
    class_name: Optional[str]
    refactor_set: RefactorSet
    source_locations: dict[tuple[str, str, str], list[int]] = field(
        default_factory=dict
    )
    source_lines: tuple[str, ...] = ()


class FuncDocsPlugin(ABC):
    plugin_id: str
    name: str
    description: str
    default_enabled = False
    order = 100

    @abstractmethod
    def create_widget(self, parent: QWidget) -> QWidget:
        """Create this plugin's independent UI."""

    @abstractmethod
    def on_function_selected(self, context: FunctionContext) -> None:
        """Analyze and display the selected function."""

    @abstractmethod
    def clear(self) -> None:
        """Clear data for the previously selected function."""
