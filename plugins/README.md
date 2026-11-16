# FuncDocs plugins

FuncDocs discovers Python modules and packages in this folder. Each is an
independent plugin and must export a `create_plugin()` function that returns a
`FuncDocsPlugin`.

Implement `plugin_id`, `name`, and `description`, then provide:

- `create_widget(parent)` to create the plugin's own UI.
- `on_function_selected(context)` to handle a selected function.
- `clear()` to remove results for the previous selection.
- Optionally, `on_diagram_item_clicked(context, category, value)` to respond
  when a relationship-diagram value is clicked.

Enabled plugins appear as separate tabs in the full-height right panel.
`FunctionContext` includes the source file, selected function and class,
`refactor_set`, source locations keyed by `(direction, category, value)`, and
the source lines. Add a new `.py` module here and restart FuncDocs to discover
it; enable it from **도구 설정**. Plugin modules are Python code and run with
the same permissions as FuncDocs, so only add plugins you trust.

The built-in **소스 구문 위치** plugin shows the selected function's complete
source immediately. Clicking a relationship value highlights the mapped line
in that code and also displays it separately; the Python AST is available in
another tab.

## Add a plugin without code-generation tools

1. Copy [`_plugin_template.py`](./_plugin_template.py) to a new file such as
   `my_plugin.py` in this folder. Do not start the new filename with `_`.
   Files that start with `_` are ignored by discovery.
2. Change `plugin_id` to a unique lowercase ID, and edit `name` and
   `description`.
3. Implement the UI in `create_widget`, update it in
   `on_function_selected`, and clear it in `clear`. Use the optional
   `on_diagram_item_clicked` hook when the plugin needs clicked diagram values.
4. Restart FuncDocs, then enable the plugin in **도구 설정**.

The **표시 설정** section in **도구 설정** controls long-line wrapping in
plugins that implement `set_wrap_long_lines`.

```python
from PyQt5.QtWidgets import QLabel

from funcdocs_plugins.api import FuncDocsPlugin, FunctionContext


class ExamplePlugin(FuncDocsPlugin):
    plugin_id = "example"
    name = "예제 도구"
    description = "예제 플러그인입니다."

    def create_widget(self, parent):
        self.label = QLabel(parent)
        return self.label

    def on_function_selected(self, context: FunctionContext):
        self.label.setText(context.function_name)

    def clear(self):
        self.label.clear()


def create_plugin():
    return ExamplePlugin()
```
