import ast

from PyQt5.QtGui import QColor, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from api.utils import select_function
from funcdocs_plugins.api import FuncDocsPlugin, FunctionContext


class SourceDetailPlugin(FuncDocsPlugin):
    plugin_id = "source_detail"
    name = "소스 구문 위치"
    description = "선택 함수 코드와 관계도 항목의 줄·AST 구조를 표시합니다."
    default_enabled = True
    order = 10

    def __init__(self):
        self.selection_label = None
        self.tabs = None
        self.function_code_view = None
        self.selected_line_view = None
        self.ast_view = None
        self._source_tree = None
        self._function_start_line = 1
        self._function_line_count = 0

    def create_widget(self, parent):
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.selection_label = QLabel()
        self.selection_label.setObjectName("pluginSummary")
        self.selection_label.setWordWrap(True)
        layout.addWidget(self.selection_label)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)

        self.function_code_view = QPlainTextEdit()
        self.function_code_view.setObjectName("codeView")
        self.function_code_view.setReadOnly(True)
        self.function_code_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.function_code_view, "함수 코드")

        self.selected_line_view = QPlainTextEdit()
        self.selected_line_view.setObjectName("codeView")
        self.selected_line_view.setReadOnly(True)
        self.selected_line_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.selected_line_view, "선택한 줄")

        self.ast_view = QPlainTextEdit()
        self.ast_view.setObjectName("codeView")
        self.ast_view.setReadOnly(True)
        self.ast_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.ast_view, "AST 구조")

        self.clear()
        return widget

    def set_wrap_long_lines(self, enabled):
        line_wrap_mode = (
            QPlainTextEdit.WidgetWidth
            if enabled
            else QPlainTextEdit.NoWrap
        )
        for view in (
            self.function_code_view,
            self.selected_line_view,
            self.ast_view,
        ):
            if view is not None:
                view.setLineWrapMode(line_wrap_mode)

    def on_function_selected(self, context: FunctionContext):
        source = "\n".join(context.source_lines)
        self._source_tree = ast.parse(source, filename=context.file_path)
        function_node = select_function(
            self._source_tree, context.function_name, context.class_name
        )["node"]
        decorator_lines = [
            decorator.lineno for decorator in function_node.decorator_list
        ]
        self._function_start_line = min(
            [function_node.lineno, *decorator_lines]
        )
        function_end_line = getattr(
            function_node, "end_lineno", function_node.lineno
        )
        function_source_lines = context.source_lines[
            self._function_start_line - 1:function_end_line
        ]
        self._function_line_count = len(function_source_lines)
        self.function_code_view.setPlainText("\n".join(function_source_lines))
        self._highlight_function_lines(())
        qualified_name = (
            f"{context.class_name}.{context.function_name}"
            if context.class_name
            else context.function_name
        )
        self.selection_label.setText(
            f"{qualified_name} - 관계도 값을 클릭하세요."
        )
        self.selected_line_view.setPlainText(
            "관계도 값을 클릭하면 해당 줄이 표시됩니다."
        )
        self._show_ast_placeholder("항목을 클릭하면 AST가 표시됩니다.")
        self.tabs.setCurrentWidget(self.function_code_view)

    def on_diagram_item_clicked(
        self, context: FunctionContext, category: str, value: str
    ):
        self.selection_label.setText(f"{category} · {value}")
        source_locations = sorted(set(context.source_locations.get(
            ("read", category, value), []
        )))
        statements = []
        source_sections = [
            self._source_line(line, context)
            for line in source_locations
        ]
        seen_statements = set()

        for line in source_locations:
            for statement in self._statements_for_line(line):
                key = (
                    type(statement).__name__,
                    statement.lineno,
                    getattr(statement, "end_lineno", statement.lineno),
                )
                if key in seen_statements:
                    continue
                seen_statements.add(key)
                statements.append(statement)

        self.selected_line_view.setPlainText(
            "\n\n".join(source_sections)
            if source_sections
            else "연결된 원본 구문을 찾을 수 없습니다."
        )
        self._highlight_function_lines(source_locations)
        ast_sections = []
        if not statements:
            self._show_ast_placeholder("연결된 AST 노드를 찾을 수 없습니다.")
            self.tabs.setCurrentWidget(self.function_code_view)
            return

        for statement in statements:
            ast_sections.append(self._render_ast(statement, context))
        self.ast_view.setPlainText("\n\n".join(ast_sections))
        self.tabs.setCurrentWidget(self.function_code_view)

    def clear(self):
        self._source_tree = None
        self._function_start_line = 1
        self._function_line_count = 0
        if self.selection_label is not None:
            self.selection_label.setText(
                "함수를 선택한 뒤 관계도 값을 클릭하세요."
            )
        if self.function_code_view is not None:
            self.function_code_view.clear()
            self._highlight_function_lines(())
        if self.selected_line_view is not None:
            self.selected_line_view.clear()
        if self.ast_view is not None:
            self._show_ast_placeholder("AST 분석을 기다리는 중입니다.")

    def _statements_for_line(self, line):
        if self._source_tree is None:
            return []

        candidates = [
            node
            for node in ast.walk(self._source_tree)
            if isinstance(node, ast.stmt)
            and node.lineno <= line <= getattr(node, "end_lineno", node.lineno)
        ]
        if not candidates:
            return []

        smallest_span = min(
            getattr(node, "end_lineno", node.lineno) - node.lineno
            for node in candidates
        )
        return [
            node
            for node in candidates
            if getattr(node, "end_lineno", node.lineno) - node.lineno
            == smallest_span
        ]

    @staticmethod
    def _source_line(line, context):
        if line < 1 or line > len(context.source_lines):
            return f"줄 {line}\n해당 줄의 원문을 찾을 수 없습니다."
        return f"줄 {line}\n{context.source_lines[line - 1]}"

    def _highlight_function_lines(self, source_lines):
        if self.function_code_view is None:
            return

        selections = []
        first_selected_block = None
        for source_line in source_lines:
            block_number = source_line - self._function_start_line
            if not 0 <= block_number < self._function_line_count:
                continue
            block = self.function_code_view.document().findBlockByNumber(
                block_number
            )
            if not block.isValid():
                continue

            cursor = QTextCursor(block)
            cursor.movePosition(
                QTextCursor.EndOfBlock, QTextCursor.KeepAnchor
            )
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setBackground(QColor("#fff0b3"))
            selection.format.setProperty(QTextFormat.FullWidthSelection, True)
            selections.append(selection)
            if first_selected_block is None:
                first_selected_block = block

        self.function_code_view.setExtraSelections(selections)
        if first_selected_block is not None:
            self.function_code_view.setTextCursor(
                QTextCursor(first_selected_block)
            )
            self.function_code_view.ensureCursorVisible()

    def _render_ast(self, root, context):
        lines = []
        self._append_ast_lines(
            root, "", "", context, lines, is_root=True
        )
        return "\n".join(lines)

    def _append_ast_lines(
        self,
        node,
        field_name,
        prefix,
        context,
        lines,
        is_root=False,
        is_last=True,
        allow_call_summary=True,
    ):
        line = self._format_ast_node(
            node, field_name, context, allow_call_summary
        )
        if is_root:
            lines.append(line)
            child_prefix = ""
        else:
            branch = "└─ " if is_last else "├─ "
            lines.append(prefix + branch + line)
            child_prefix = prefix + ("   " if is_last else "│  ")

        children = self._ast_children(node)
        for index, (child_field, child_node) in enumerate(children):
            child_is_last = index == len(children) - 1
            if isinstance(child_node, list):
                branch = "└─ " if child_is_last else "├─ "
                grouped_nodes = ", ".join(
                    self._format_grouped_node(value, context)
                    for value in child_node
                )
                lines.append(
                    f"{child_prefix}{branch}{child_field}: {grouped_nodes}"
                )
                continue

            self._append_ast_lines(
                child_node,
                child_field,
                child_prefix,
                context,
                lines,
                is_last=child_is_last,
                allow_call_summary=(
                    allow_call_summary and not isinstance(node, ast.Call)
                ),
            )

    def _ast_children(self, node):
        children = []
        for field_name, value in ast.iter_fields(node):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and field_name == "body"
            ):
                continue
            if isinstance(value, ast.expr_context):
                continue
            if isinstance(value, ast.AST):
                children.append((field_name, value))
                continue
            if not isinstance(value, list):
                continue

            nodes = [
                child
                for child in value
                if isinstance(child, ast.AST)
                and not isinstance(child, ast.expr_context)
            ]
            if not nodes:
                continue
            if len(nodes) == 1:
                children.append((
                    self._list_field_name(field_name, 0, 1),
                    nodes[0],
                ))
            elif all(self._is_ast_leaf(child) for child in nodes):
                children.append((field_name, nodes))
            else:
                children.extend(
                    (
                        self._list_field_name(field_name, index, len(nodes)),
                        child,
                    )
                    for index, child in enumerate(nodes)
                )
        return children

    @staticmethod
    def _is_ast_leaf(node):
        for _, value in ast.iter_fields(node):
            if isinstance(value, ast.expr_context):
                continue
            if isinstance(value, ast.AST):
                return False
            if isinstance(value, list) and any(
                isinstance(child, ast.AST)
                and not isinstance(child, ast.expr_context)
                for child in value
            ):
                return False
        return True

    @staticmethod
    def _list_field_name(field_name, index, count):
        if field_name == "targets":
            return "target" if count == 1 else f"target[{index}]"
        if field_name == "args":
            return "args" if count == 1 else f"arg[{index}]"
        if field_name == "keywords":
            return "keyword" if count == 1 else f"keyword[{index}]"
        if field_name == "body":
            return f"statement[{index}]"
        return f"{field_name}[{index}]"

    def _format_ast_node(self, node, field_name, context, allow_call_summary):
        description = self._node_display(node, context)
        if field_name:
            description = f"{field_name}: {description}"

        annotation = self._node_annotation(node, allow_call_summary)
        if annotation:
            description += f" ← {annotation}"
        return description

    def _format_grouped_node(self, node, context):
        return self._node_display(node, context)

    def _node_display(self, node, context):
        if isinstance(node, ast.Name):
            return f"Name({node.id}, {type(node.ctx).__name__})"
        if isinstance(node, ast.Attribute):
            base = self._attribute_base(node.value)
            return f"Attribute({base}.{node.attr})" if base else (
                f"Attribute(.{node.attr})"
            )
        if isinstance(node, ast.Constant):
            segment = ast.get_source_segment(
                "\n".join(context.source_lines), node
            )
            return f"Constant({segment if segment is not None else repr(node.value)})"
        return type(node).__name__

    @staticmethod
    def _attribute_base(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = SourceDetailPlugin._attribute_base(node.value)
            return f"{base}.{node.attr}" if base else f".{node.attr}"
        return ""

    def _node_annotation(self, node, allow_call_summary):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Store):
                return "쓰기 (지역변수 생성)"
            if isinstance(node.ctx, ast.Load):
                return "읽기"
            if isinstance(node.ctx, ast.Del):
                return "삭제"
        if isinstance(node, ast.Call) and allow_call_summary:
            depth = self._call_chain_depth(node)
            if depth > 1:
                return f"{depth}단 중첩 호출 체인"
            return "함수 호출"
        return ""

    @staticmethod
    def _call_chain_depth(node):
        child_depths = [
            SourceDetailPlugin._call_chain_depth(child)
            for child in ast.iter_child_nodes(node)
        ]
        nested_depth = max(child_depths, default=0)
        return nested_depth + 1 if isinstance(node, ast.Call) else nested_depth

    def _show_ast_placeholder(self, message):
        if self.ast_view is None:
            return
        self.ast_view.setPlainText(message)


def create_plugin():
    return SourceDetailPlugin()
