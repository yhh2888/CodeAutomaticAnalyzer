from PyQt5.QtWidgets import QPlainTextEdit

from funcdocs_plugins.api import FuncDocsPlugin, FunctionContext


class ExamplePlugin(FuncDocsPlugin):
    plugin_id = "replace_with_unique_id"
    name = "내 플러그인"
    description = "이 플러그인이 보여줄 내용을 설명합니다."
    default_enabled = False

    def __init__(self):
        self.view = None

    def create_widget(self, parent):
        self.view = QPlainTextEdit(parent)
        self.view.setReadOnly(True)
        self.set_wrap_long_lines(True)
        return self.view

    def on_function_selected(self, context: FunctionContext):
        self.view.setPlainText(
            f"선택 함수: {context.function_name}\n"
            f"파일: {context.file_path}"
        )

    def on_diagram_item_clicked(
        self, context: FunctionContext, category: str, value: str
    ):
        line_numbers = sorted(set(
            context.source_locations.get(("read", category, value), [])
        ))
        source_lines = [
            f"{line}: {context.source_lines[line - 1]}"
            for line in line_numbers
            if 1 <= line <= len(context.source_lines)
        ]
        self.view.setPlainText(
            "\n".join(source_lines) or f"{category}: {value}"
        )

    def set_wrap_long_lines(self, enabled: bool):
        mode = (
            QPlainTextEdit.WidgetWidth
            if enabled
            else QPlainTextEdit.NoWrap
        )
        if self.view is not None:
            self.view.setLineWrapMode(mode)

    def clear(self):
        if self.view is not None:
            self.view.clear()


def create_plugin():
    return ExamplePlugin()
