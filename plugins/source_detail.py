import ast
import io
import json
import os
import re
import tokenize

from PyQt5.QtCore import Qt, QSettings, pyqtSignal
from PyQt5.QtGui import QColor, QTextCursor, QTextFormat
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api.utils import select_function
from funcdocs_plugins.api import (
    CATEGORY_COLORS,
    FuncDocsPlugin,
    FunctionContext,
)


def _ast_feature(node):
    if isinstance(node, ast.expr_context):
        return None

    fields = []
    for field_name, value in ast.iter_fields(node):
        if isinstance(value, ast.expr_context):
            continue
        if isinstance(value, ast.AST):
            child = _ast_feature(value)
            if child is not None:
                fields.append((field_name, child))
        elif isinstance(value, list):
            children = [
                _ast_feature(child)
                for child in value
                if isinstance(child, ast.AST)
                and not isinstance(child, ast.expr_context)
            ]
            fields.append((field_name, children))
    return [type(node).__name__, fields]


class ClickableCodeView(QPlainTextEdit):
    line_clicked = pyqtSignal(int, int)

    def mousePressEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        block_number = cursor.blockNumber()
        column = cursor.positionInBlock()
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.line_clicked.emit(block_number, column)


class ConditionCandidateDialog(QDialog):
    def __init__(
        self, nodes, source_lines, parent=None, conditions=None,
        expression=None, candidate_name="",
    ):
        super().__init__(parent)
        self.setWindowTitle(
            "조건 후보 수정" if conditions is not None else "조건 후보 구성"
        )
        self.setMinimumSize(680, 500)
        self._conditions = []

        layout = QVBoxLayout(self)
        description = QLabel(
            "각 조건 요소는 선택한 AST 구문과 그 하위 노드입니다. "
            "아래 식에서 C1, C2처럼 참조해 NOT, AND, OR와 괄호로 "
            "원하는 조건식을 구성하세요. AST 형태만 비교하며 변수 이름, "
            "읽기/쓰기 흐름, 줄 위치는 조건에 포함하지 않습니다."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        layout.addWidget(QLabel("조건명"))
        self.name_view = QLineEdit(candidate_name)
        self.name_view.setPlaceholderText("예: 데이터베이스 호출")
        layout.addWidget(self.name_view)

        self.condition_view = QTreeWidget()
        self.condition_view.setHeaderLabels(["조건 ID", "AST 요소"])
        self.condition_view.setRootIsDecorated(False)
        self.condition_view.setColumnWidth(0, 75)
        for node in nodes:
            pattern = ast.dump(node, include_attributes=False)
            source = ast.get_source_segment("\n".join(source_lines), node)
            if source is None:
                source = type(node).__name__
            condition = {
                "node_type": type(node).__name__,
                "ast": pattern,
                "feature": json.dumps(
                    _ast_feature(node), ensure_ascii=False
                ),
                "source": " ".join(source.split()),
                "line": getattr(node, "lineno", 0),
            }
            self._add_condition_row(condition)
        for condition in conditions or ():
            self._add_condition_row(condition)
        layout.addWidget(self.condition_view, stretch=1)

        layout.addWidget(QLabel("조건식"))
        self.expression_view = QPlainTextEdit()
        self.expression_view.setPlaceholderText(
            "예: (C1 AND NOT C2) OR C3"
        )
        self.expression_view.setMaximumHeight(100)
        if expression is None:
            expression = " AND ".join(
                f"C{index}"
                for index in range(1, len(self._conditions) + 1)
            )
        self.expression_view.setPlainText(expression)
        layout.addWidget(self.expression_view)
        syntax_note = QLabel(
            "문법: C1, C2, ... / NOT / AND / OR / 괄호. "
            "AND가 OR보다 먼저 계산됩니다."
        )
        syntax_note.setObjectName("mutedLabel")
        layout.addWidget(syntax_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_condition_row(self, condition):
        feature = condition.get("feature")
        if not isinstance(feature, str):
            try:
                parsed = ast.parse(condition["source"])
            except SyntaxError:
                parsed = None
            if parsed is not None:
                source_node = next(
                    (
                        node for node in ast.walk(parsed)
                        if type(node).__name__ == condition["node_type"]
                    ),
                    None,
                )
                if source_node is not None:
                    feature = json.dumps(
                        _ast_feature(source_node), ensure_ascii=False
                    )
        condition = {
            "node_type": condition["node_type"],
            "ast": condition["ast"],
            "feature": feature,
            "source": condition["source"],
            "line": condition["line"],
        }
        index = len(self._conditions) + 1
        item = QTreeWidgetItem(self.condition_view, [
            f"C{index}",
            f"{condition['node_type']} · {condition['source']} "
            f"(줄 {condition['line']})",
        ])
        item.setToolTip(1, condition["ast"])
        self._conditions.append(condition)

    def selected_conditions(self):
        return list(self._conditions)

    def expression(self):
        return self.expression_view.toPlainText().strip()

    def candidate_name(self):
        return self.name_view.text().strip()


class ConditionMatchDialog(QDialog):
    def __init__(
        self, candidate, evidence, source_text, statement_text, parent=None
    ):
        super().__init__(parent)
        self.setWindowTitle(
            f"조건 일치 이유 - {SourceDetailPlugin._condition_candidate_label(candidate)}"
        )
        self.setMinimumSize(680, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"조건명: {SourceDetailPlugin._condition_candidate_label(candidate)}"
        ))
        layout.addWidget(QLabel(
            f"적용 식: {SourceDetailPlugin._candidate_expression(candidate)}"
        ))
        layout.addWidget(QLabel("판정 단위: 아래 구문 하나"))
        statement_view = QPlainTextEdit()
        statement_view.setReadOnly(True)
        statement_view.setPlainText(statement_text)
        statement_view.setMaximumHeight(120)
        layout.addWidget(statement_view)

        evidence_view = QTreeWidget()
        evidence_view.setHeaderLabels(["요소", "판정", "AST 구조 특징"])
        evidence_view.setColumnWidth(0, 70)
        evidence_view.setColumnWidth(1, 80)
        for index, (condition, matched_nodes) in enumerate(
            zip(candidate.get("conditions", ()), evidence),
            start=1,
        ):
            matched_source = " · ".join(
                " ".join(
                    (ast.get_source_segment(source_text, node) or "").split()
                )
                for node in matched_nodes
            )
            description = (
                f"{condition['node_type']} · "
                f"{condition['source']}"
            )
            if matched_source:
                description += f"  →  발견: {matched_source}"
            item = QTreeWidgetItem(evidence_view, [
                f"C{index}",
                "참" if matched_nodes else "거짓",
                description,
            ])
            item.setToolTip(2, condition.get("feature", condition["ast"]))
        layout.addWidget(evidence_view, stretch=1)
        layout.addWidget(QLabel(
            "최종 판정: 조건식이 참이므로 이 구문은 조건 후보에 해당합니다."
        ))
        note = QLabel(
            "변수명, 읽기/쓰기 흐름, 줄 위치는 비교하지 않고 AST 형태만 비교합니다."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(self.accept)
        layout.addWidget(buttons)


class SourceDetailPlugin(FuncDocsPlugin):
    plugin_id = "source_detail"
    name = "소스 구문 위치"
    description = (
        "선택한 원문 구문과 AST를 연결하고 조건 후보를 관리합니다."
    )
    default_enabled = True
    order = 10

    def __init__(self):
        self.selection_label = None
        self.tabs = None
        self.function_code_view = None
        self.selected_line_view = None
        self.ast_view = None
        self.ast_source_view = None
        self._source_tree = None
        self._source_tokens = ()
        self._function_node = None
        self._comment_ranges = {}
        self._function_start_line = 1
        self._function_line_count = 0
        self._context = None
        self._line_elements = {}
        self._element_ranges = []
        self._related_source_lines = ()
        self._diagram_item_callback = None
        self._condition_candidates_callback = None
        self._source_code_click_in_progress = False
        self._ast_nodes = {}
        self._ast_items = {}
        self._selected_ast_node = None
        self._updating_ast_from_source = False
        self._condition_candidates = []
        self._candidate_settings = QSettings(
            "CodeAutomaticAnalyzer", "FuncDocs"
        )
        self._candidate_settings_key = None
        self._condition_candidate_occurrences = {}
        self.ast_page = None
        self.candidate_page = None
        self.candidate_view = None
        self.add_candidate_button = None

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

        self.function_code_view = ClickableCodeView()
        self.function_code_view.setObjectName("codeView")
        self.function_code_view.setReadOnly(True)
        self.function_code_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.function_code_view.line_clicked.connect(
            self._on_function_code_line_clicked
        )
        self.tabs.addTab(self.function_code_view, "함수 코드")

        self.selected_line_view = QPlainTextEdit()
        self.selected_line_view.setObjectName("codeView")
        self.selected_line_view.setReadOnly(True)
        self.selected_line_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.tabs.addTab(self.selected_line_view, "선택한 줄")

        self.ast_page = QWidget()
        ast_layout = QVBoxLayout(self.ast_page)
        ast_layout.setContentsMargins(0, 0, 0, 0)
        self.ast_view = QTreeWidget()
        self.ast_view.setObjectName("codeView")
        self.ast_view.setHeaderLabels(["AST 노드와 원문 위치"])
        self.ast_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.ast_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.ast_view.setStyleSheet(
            "QTreeWidget::item:selected {"
            "background-color: #fff0b3;"
            "color: #182b49;"
            "}"
        )
        self.ast_view.currentItemChanged.connect(
            self._on_ast_tree_selection_changed
        )
        self.ast_view.itemSelectionChanged.connect(
            self._update_add_candidate_button
        )
        ast_splitter = QSplitter(Qt.Horizontal)
        ast_splitter.addWidget(self.ast_view)
        self.ast_source_view = QPlainTextEdit()
        self.ast_source_view.setObjectName("codeView")
        self.ast_source_view.setReadOnly(True)
        self.ast_source_view.setLineWrapMode(QPlainTextEdit.NoWrap)
        ast_splitter.addWidget(self.ast_source_view)
        ast_splitter.setStretchFactor(0, 3)
        ast_splitter.setStretchFactor(1, 2)
        ast_layout.addWidget(ast_splitter, stretch=1)
        self.add_candidate_button = QPushButton("선택 AST들을 조건 후보로 추가")
        self.add_candidate_button.clicked.connect(
            self._add_selected_ast_candidate
        )
        ast_layout.addWidget(self.add_candidate_button)
        self.tabs.addTab(self.ast_page, "AST 구조")

        self.candidate_page = QWidget()
        candidate_layout = QVBoxLayout(self.candidate_page)
        candidate_layout.setContentsMargins(0, 0, 0, 0)
        candidate_layout.addWidget(QLabel(
            "조건 후보는 함수 간 공유됩니다. 선택한 AST 구조 조건을 "
            "현재 함수에서 AND/OR로 검색하고 일치 항목을 Rn으로 표시합니다."
        ))
        self.candidate_view = QListWidget()
        self.candidate_view.itemDoubleClicked.connect(
            self._edit_condition_candidate
        )
        candidate_layout.addWidget(self.candidate_view, stretch=1)
        edit_candidate_button = QPushButton("선택 후보 수정")
        edit_candidate_button.clicked.connect(
            self._edit_selected_condition_candidate
        )
        candidate_layout.addWidget(edit_candidate_button)
        remove_candidate_button = QPushButton("선택 후보 삭제")
        remove_candidate_button.clicked.connect(
            self._remove_selected_condition_candidate
        )
        candidate_layout.addWidget(remove_candidate_button)
        self.tabs.addTab(self.candidate_page, "조건 후보")

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
            self.ast_source_view,
        ):
            if view is not None:
                view.setLineWrapMode(line_wrap_mode)

    def on_function_selected(self, context: FunctionContext):
        self._context = context
        source = "\n".join(context.source_lines)
        self._source_tree = ast.parse(source, filename=context.file_path)
        self._source_tokens = tuple(
            tokenize.generate_tokens(io.StringIO(source).readline)
        )
        self._build_comment_ranges(context)
        function_node = select_function(
            self._source_tree, context.function_name, context.class_name
        )["node"]
        self._function_node = function_node
        self._candidate_settings_key = self._get_candidate_settings_key()
        self._condition_candidates = self._load_condition_candidates()
        self._refresh_candidate_view()
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
        self._build_source_highlights(context)
        self._highlight_function_lines(())
        qualified_name = (
            f"{context.class_name}.{context.function_name}"
            if context.class_name
            else context.function_name
        )
        self.selection_label.setText(
            f"{qualified_name} - 원문 구문을 선택하면 AST와 연결됩니다."
        )
        self.selected_line_view.setPlainText(
            "원문이나 AST 노드를 선택하면 해당 위치가 표시됩니다."
        )
        self._show_ast_placeholder("원문 구문을 선택하면 AST가 표시됩니다.")
        self.tabs.setCurrentWidget(self.function_code_view)

    def set_diagram_item_callback(self, callback):
        self._diagram_item_callback = callback

    def set_condition_candidates_callback(self, callback):
        self._condition_candidates_callback = callback

    def on_diagram_item_clicked(
        self, context: FunctionContext, category: str, value: str
    ):
        if self._source_code_click_in_progress:
            return
        if category == "Rn":
            self._on_condition_candidate_diagram_clicked(value)
            return
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
        if not statements:
            self._show_ast_placeholder("연결된 AST 노드를 찾을 수 없습니다.")
            return

        self._show_ast_nodes(statements, statements[0])
        self._highlight_ast_node_in_source(statements[0])

    def clear(self):
        self._source_tree = None
        self._source_tokens = ()
        self._function_node = None
        self._context = None
        self._comment_ranges = {}
        self._function_start_line = 1
        self._function_line_count = 0
        self._line_elements = {}
        self._element_ranges = []
        self._related_source_lines = ()
        self._ast_nodes = {}
        self._ast_items = {}
        self._selected_ast_node = None
        self._updating_ast_from_source = False
        self._condition_candidates = []
        self._candidate_settings_key = None
        self._condition_candidate_occurrences = {}
        if self.selection_label is not None:
            self.selection_label.setText(
                "함수를 선택한 뒤 관계도 값을 클릭하세요."
            )
        if self.function_code_view is not None:
            self.function_code_view.clear()
            self._highlight_function_lines(())
        if self.selected_line_view is not None:
            self.selected_line_view.clear()
        if self.candidate_view is not None:
            self.candidate_view.clear()
        if self.ast_view is not None:
            self._show_ast_placeholder("AST 분석을 기다리는 중입니다.")

    def _statements_for_line(self, line):
        if self._source_tree is None:
            return []

        candidates = []
        for node in ast.walk(self._source_tree):
            if not isinstance(node, ast.stmt):
                continue
            start_line, _, end_line, _ = self._statement_source_range(node)
            if start_line <= line <= end_line:
                candidates.append(node)
        if not candidates:
            return []

        smallest_span = min(
            self._statement_source_range(node)[2]
            - self._statement_source_range(node)[0]
            for node in candidates
        )
        return sorted(
            [
            node
            for node in candidates
            if self._statement_source_range(node)[2]
            - self._statement_source_range(node)[0] == smallest_span
            ],
            key=lambda node: self._statement_source_range(node)[1],
        )

    @staticmethod
    def _ast_column_to_character(source_line, byte_column):
        prefix = source_line.encode("utf-8")[:byte_column]
        return len(prefix.decode("utf-8", errors="ignore"))

    def _statement_source_range(self, node):
        start_line = node.lineno
        start_column = getattr(node, "col_offset", 0)
        end_line = getattr(node, "end_lineno", start_line)
        end_column = getattr(node, "end_col_offset", start_column)
        compound_types = (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.With,
            ast.AsyncWith,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.Try,
            ast.Match,
        )
        if hasattr(ast, "TryStar"):
            compound_types += (ast.TryStar,)
        if not isinstance(node, compound_types):
            return start_line, start_column, end_line, end_column

        body = getattr(node, "body", ())
        if isinstance(node, ast.Match) and node.cases:
            first_case = node.cases[0]
            boundary = (
                first_case.pattern.lineno,
                first_case.pattern.col_offset,
            )
        elif body:
            first_statement = body[0]
            boundary = (
                first_statement.lineno,
                first_statement.col_offset,
            )
        else:
            return start_line, start_column, start_line, start_column
        boundary_line, boundary_byte_column = boundary
        boundary_column = self._ast_column_to_character(
            self._context.source_lines[boundary_line - 1],
            boundary_byte_column,
        )
        nesting = 0
        header_colon = None
        for token in self._source_tokens:
            token_line, token_column = token.start
            if (token_line, token_column) < (
                start_line,
                self._ast_column_to_character(
                    self._context.source_lines[start_line - 1],
                    start_column,
                ),
            ):
                continue
            if (token_line, token_column) >= (
                boundary_line,
                boundary_column,
            ):
                break
            if token.type == tokenize.OP:
                if token.string in "([{":
                    nesting += 1
                elif token.string in ")]}":
                    nesting = max(0, nesting - 1)
                elif token.string == ":" and nesting == 0:
                    header_colon = token.end
        if header_colon is None:
            return start_line, start_column, start_line, start_column
        end_line, end_character_column = header_colon
        end_column = len(
            self._context.source_lines[end_line - 1][
                :end_character_column
            ].encode("utf-8")
        )
        return start_line, start_column, end_line, end_column

    def _statement_source_segment(self, node):
        start_line, start_column, end_line, end_column = (
            self._statement_source_range(node)
        )
        start_character_column = self._ast_column_to_character(
            self._context.source_lines[start_line - 1], start_column
        )
        end_character_column = self._ast_column_to_character(
            self._context.source_lines[end_line - 1], end_column
        )
        if start_line == end_line:
            return self._context.source_lines[start_line - 1][
                start_character_column:end_character_column
            ]
        return "\n".join(
            [
                self._context.source_lines[start_line - 1][
                    start_character_column:
                ],
                *self._context.source_lines[start_line:end_line - 1],
                self._context.source_lines[end_line - 1][
                    :end_character_column
                ],
            ]
        )

    def _build_source_highlights(self, context):
        self._line_elements = {}
        self._element_ranges = []

        for category, elements in context.refactor_set[0].items():
            if category not in CATEGORY_COLORS:
                continue
            for element in elements:
                value = element[1]
                if value == "self":
                    continue
                source_lines = context.source_locations.get(
                    ("read", category, value), ()
                )
                for source_line in source_lines:
                    if not 1 <= source_line <= len(context.source_lines):
                        continue
                    elements_for_line = self._line_elements.setdefault(
                        source_line, []
                    )
                    if (category, value) not in elements_for_line:
                        elements_for_line.append((category, value))

                    source = context.source_lines[source_line - 1]
                    start = 0
                    while value and (start := source.find(value, start)) >= 0:
                        self._element_ranges.append((
                            source_line, start, start + len(value), category,
                            value,
                        ))
                        start += len(value)

        self._related_source_lines = tuple(sorted(self._line_elements))

    def _build_comment_ranges(self, context):
        self._comment_ranges = {}
        source = "\n".join(context.source_lines)
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            line, start = token.start
            _, end = token.end
            source_line = context.source_lines[line - 1]
            start_column = len(
                source_line[:start].encode("utf-16-le")
            ) // 2
            end_column = len(
                source_line[:end].encode("utf-16-le")
            ) // 2
            self._comment_ranges.setdefault(line, []).append(
                (start_column, end_column)
            )

    def _on_function_code_line_clicked(self, block_number, column):
        line = self._function_start_line + block_number
        if self._context is None:
            return
        if any(
            start <= column < end
            for start, end in self._comment_ranges.get(line, ())
        ):
            return

        statements = self._statements_for_line(line)
        selected_statement = self._statement_at_position(line, column)
        if selected_statement is not None:
            statements = [selected_statement]
        elif statements:
            selected_statement = statements[0]

        self.selected_line_view.setPlainText(
            self._source_line(line, self._context)
        )
        self.selection_label.setText(f"원문 줄 {line} · 구문 선택")
        self._highlight_function_lines((line,))
        self._show_ast_nodes(statements, selected_statement)
        if self._node_has_source_location(selected_statement):
            self._highlight_ast_node_in_source(selected_statement)

        elements = self._line_elements.get(line, ())
        if not elements or self._diagram_item_callback is None:
            return

        matching_ranges = [
            item for item in self._element_ranges
            if item[0] == line and item[1] <= column < item[2]
        ]
        if matching_ranges:
            _, _, _, category, value = max(
                matching_ranges, key=lambda item: item[2] - item[1]
            )
            selected = (category, value)
        else:
            selected = elements[0]
        self._source_code_click_in_progress = True
        try:
            self._diagram_item_callback(*selected)
        finally:
            self._source_code_click_in_progress = False

    def _statement_at_position(self, line, column):
        if self._source_tree is None or not 1 <= line <= len(
            self._context.source_lines
        ):
            return None

        source_line = self._context.source_lines[line - 1]
        utf16_column = 0
        prefix = []
        for character in source_line:
            width = len(character.encode("utf-16-le")) // 2
            if utf16_column + width > column:
                break
            prefix.append(character)
            utf16_column += width
        byte_column = len("".join(prefix).encode("utf-8"))

        candidates = []
        for index, node in enumerate(ast.walk(self._source_tree)):
            if not isinstance(node, ast.stmt):
                continue
            start_line, start_column, end_line, end_column = (
                self._statement_source_range(node)
            )
            if not start_line <= line <= end_line:
                continue
            if line == start_line and byte_column < start_column:
                continue
            if line == end_line and byte_column > end_column:
                continue
            candidates.append((
                end_line - start_line,
                end_column - start_column if start_line == end_line else 0,
                index,
                node,
            ))

        if not candidates:
            return None
        return min(candidates, key=lambda item: item[:3])[3]

    def _show_ast_nodes(self, roots, selected_node=None):
        self.ast_view.clear()
        self._ast_nodes = {}
        self._ast_items = {}
        self._selected_ast_node = selected_node
        self._updating_ast_from_source = True
        selected_item = None
        for root in roots:
            item = self._add_ast_tree_item(None, root, "")
            if root is selected_node:
                selected_item = item
        if selected_node is not None:
            selected_item = self._find_ast_item(selected_node)
        self.ast_view.expandAll()
        if selected_item is not None:
            self.ast_view.setCurrentItem(selected_item)
        self._updating_ast_from_source = False
        self._update_add_candidate_button()
        if not roots:
            self._show_ast_placeholder("선택 위치에 AST 구문이 없습니다.")

    def _add_ast_tree_item(self, parent, node, field_name):
        label = self._ast_tree_label(node, field_name)
        item = (
            QTreeWidgetItem(parent, [label])
            if parent is not None
            else QTreeWidgetItem(self.ast_view, [label])
        )
        item.setData(0, Qt.UserRole, id(node))
        self._ast_nodes[id(node)] = node
        self._ast_items[id(node)] = item

        for field, value in ast.iter_fields(node):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and field == "body"
            ):
                continue
            if isinstance(value, ast.expr_context):
                continue
            if isinstance(value, ast.AST):
                self._add_ast_tree_item(item, value, field)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    if not isinstance(child, ast.AST) or isinstance(
                        child, ast.expr_context
                    ):
                        continue
                    self._add_ast_tree_item(
                        item, child, f"{field}[{index}]"
                    )
        return item

    def _find_ast_item(self, node):
        return self._ast_items.get(id(node))

    def _ast_tree_label(self, node, field_name):
        description = self._node_display(node, self._context)
        if field_name:
            description = f"{field_name}: {description}"
        annotation = self._node_annotation(node, True)
        if annotation:
            description += f" ← {annotation}"
        if self._node_has_source_location(node):
            if isinstance(node, ast.stmt):
                start, _, end, _ = self._statement_source_range(node)
            else:
                start = node.lineno
                end = getattr(node, "end_lineno", start)
            description += (
                f"  [줄 {start}" if start == end
                else f"  [줄 {start}-{end}"
            ) + "]"
        return description

    @staticmethod
    def _node_has_source_location(node):
        return node is not None and getattr(node, "lineno", None) is not None

    def _on_ast_tree_selection_changed(self, current, _previous):
        if current is None or self._updating_ast_from_source:
            return
        node = self._ast_nodes.get(current.data(0, Qt.UserRole))
        self._selected_ast_node = node
        self._update_add_candidate_button()
        source_node = node
        parent = current.parent()
        while (
            source_node is not None
            and not self._node_has_source_location(source_node)
            and parent is not None
        ):
            source_node = self._ast_nodes.get(parent.data(0, Qt.UserRole))
            parent = parent.parent()
        if source_node is None or not self._node_has_source_location(
            source_node
        ):
            return
        self._highlight_ast_node_in_source(source_node)

    def _update_add_candidate_button(self):
        if self.add_candidate_button is None:
            return
        self.add_candidate_button.setEnabled(any(
            self._node_has_source_location(
                self._ast_nodes.get(item.data(0, Qt.UserRole))
            )
            for item in self.ast_view.selectedItems()
        ))

    def _highlight_ast_node_in_source(self, node):
        if isinstance(node, ast.stmt):
            (
                start_line,
                start_byte_column,
                end_line,
                end_byte_column,
            ) = self._statement_source_range(node)
        else:
            start_line = node.lineno
            end_line = getattr(node, "end_lineno", start_line)
            start_byte_column = getattr(node, "col_offset", 0)
            end_byte_column = getattr(
                node,
                "end_col_offset",
                len(self._context.source_lines[end_line - 1].encode("utf-8")),
            )
        if (
            start_line < self._function_start_line
            or end_line >= self._function_start_line + self._function_line_count
        ):
            return

        self._highlight_function_lines(())
        start_block = self.function_code_view.document().findBlockByNumber(
            start_line - self._function_start_line
        )
        end_block = self.function_code_view.document().findBlockByNumber(
            end_line - self._function_start_line
        )
        if not start_block.isValid() or not end_block.isValid():
            return

        start_column = self._ast_column_to_utf16(
            self._context.source_lines[start_line - 1],
            start_byte_column,
        )
        end_column = self._ast_column_to_utf16(
            self._context.source_lines[end_line - 1],
            end_byte_column,
        )
        self._add_ast_source_highlights(
            self.function_code_view,
            start_line,
            end_line,
            start_column,
            end_column,
            self._function_start_line,
        )
        self.selected_line_view.setPlainText("\n".join(
            self._source_line(line, self._context)
            for line in range(start_line, end_line + 1)
        ))

        source_text = "\n".join(
            self._context.source_lines[start_line - 1:end_line]
        )
        self.ast_source_view.setPlainText(source_text)
        self._add_ast_source_highlights(
            self.ast_source_view,
            start_line,
            end_line,
            start_column,
            end_column,
            start_line,
        )

    def _add_ast_source_highlights(
        self, view, start_line, end_line, start_column, end_column,
        first_source_line,
    ):
        selections = view.extraSelections()
        for source_line in range(start_line, end_line + 1):
            block_number = source_line - first_source_line
            block = view.document().findBlockByNumber(block_number)
            if not block.isValid():
                continue

            source = self._context.source_lines[source_line - 1]
            range_start = start_column if source_line == start_line else 0
            range_end = (
                end_column
                if source_line == end_line
                else len(source.encode("utf-16-le")) // 2
            )
            segments = [(range_start, range_end)]
            for comment_start, comment_end in self._comment_ranges.get(
                source_line, ()
            ):
                remaining = []
                for segment_start, segment_end in segments:
                    if (
                        comment_end <= segment_start
                        or comment_start >= segment_end
                    ):
                        remaining.append((segment_start, segment_end))
                        continue
                    if segment_start < comment_start:
                        remaining.append((segment_start, comment_start))
                    if comment_end < segment_end:
                        remaining.append((comment_end, segment_end))
                segments = remaining

            for segment_start, segment_end in segments:
                if segment_start >= segment_end:
                    continue
                cursor = QTextCursor(block)
                cursor.setPosition(block.position() + segment_start)
                cursor.setPosition(
                    block.position() + segment_end, QTextCursor.KeepAnchor
                )
                selection = QTextEdit.ExtraSelection()
                selection.cursor = cursor
                selection.format.setBackground(QColor("#fff0b3"))
                selections.append(selection)
        view.setExtraSelections(selections)

    @staticmethod
    def _ast_column_to_utf16(source_line, byte_column):
        utf16_column = 0
        byte_offset = 0
        for character in source_line:
            encoded_width = len(character.encode("utf-8"))
            if byte_offset + encoded_width > byte_column:
                break
            byte_offset += encoded_width
            utf16_column += len(character.encode("utf-16-le")) // 2
        return utf16_column

    @staticmethod
    def _get_candidate_settings_key():
        return "diagramConditionCandidates"

    def _load_condition_candidates(self):
        migrating = False
        raw = self._candidate_settings.value(
            self._candidate_settings_key, None, type=str
        )
        if raw is None:
            migrating = True
            legacy_candidates = []
            legacy_prefix = f"{self._candidate_settings_key}/"
            for key in self._candidate_settings.allKeys():
                if not key.startswith(legacy_prefix):
                    continue
                legacy_raw = self._candidate_settings.value(
                    key, "[]", type=str
                )
                try:
                    stored_candidates = json.loads(legacy_raw)
                except json.JSONDecodeError as error:
                    QMessageBox.warning(
                        self.tabs,
                        "조건 후보 읽기 실패",
                        f"이전 조건 후보를 읽을 수 없습니다.\n{error}",
                    )
                    continue
                if not isinstance(stored_candidates, list):
                    QMessageBox.warning(
                        self.tabs,
                        "조건 후보 읽기 실패",
                        "이전 조건 후보 형식이 올바르지 않습니다.",
                    )
                    continue
                legacy_candidates.extend(stored_candidates)
            raw = json.dumps(legacy_candidates, ensure_ascii=False)
        try:
            candidates = json.loads(raw)
        except json.JSONDecodeError as error:
            QMessageBox.warning(
                self.tabs,
                "조건 후보 읽기 실패",
                f"저장된 조건 후보를 읽을 수 없습니다.\n{error}",
            )
            return []
        if not isinstance(candidates, list):
            QMessageBox.warning(
                self.tabs,
                "조건 후보 읽기 실패",
                "저장된 조건 후보 형식이 올바르지 않습니다.",
            )
            return []
        valid_candidates = []
        for candidate in candidates:
            if not (
                isinstance(candidate, dict)
                and isinstance(candidate.get("node_type"), str)
                and isinstance(candidate.get("ast"), str)
                and isinstance(candidate.get("source"), str)
                and isinstance(candidate.get("line"), int)
            ):
                continue
            conditions = candidate.get("conditions")
            if conditions is not None and not (
                isinstance(conditions, list)
                and conditions
                and all(
                    isinstance(condition, dict)
                    and isinstance(condition.get("node_type"), str)
                    and isinstance(condition.get("ast"), str)
                    and isinstance(condition.get("source"), str)
                    and isinstance(condition.get("line"), int)
                    and (
                        condition.get("feature") is None
                        or isinstance(condition.get("feature"), str)
                    )
                    and (
                        condition.get("operator") is None
                        or condition["operator"] in {"AND", "OR"}
                    )
                    for condition in conditions
                )
            ):
                continue
            if conditions is not None:
                expression = candidate.get("expression")
                if expression is not None and not isinstance(expression, str):
                    continue
                try:
                    self._evaluate_condition_expression(
                        self._candidate_expression(candidate),
                        [True] * len(conditions),
                    )
                except ValueError:
                    continue
            valid_candidates.append(candidate)
        if len(valid_candidates) != len(candidates):
            QMessageBox.warning(
                self.tabs,
                "조건 후보 읽기 실패",
                "형식이 올바르지 않은 저장 후보를 건너뛰었습니다.",
            )
        unique_candidates = []
        seen_candidates = set()
        for candidate in valid_candidates:
            conditions = candidate.get("conditions")
            signature = (
                tuple(
                    (
                        condition["node_type"],
                        condition.get("feature", condition["ast"]),
                    )
                    for condition in conditions
                )
                if conditions is not None
                else (candidate["node_type"],)
            ) + (self._candidate_expression(candidate),)
            if signature in seen_candidates:
                continue
            seen_candidates.add(signature)
            unique_candidates.append(candidate)
        if migrating or len(unique_candidates) != len(valid_candidates):
            self._candidate_settings.setValue(
                self._candidate_settings_key,
                json.dumps(unique_candidates, ensure_ascii=False),
            )
            self._candidate_settings.sync()
            if self._candidate_settings.status() != QSettings.NoError:
                QMessageBox.warning(
                    self.tabs,
                    "조건 후보 저장 실패",
                    "공유 조건 후보를 저장하지 못했습니다.",
                )
        return unique_candidates

    def _refresh_candidate_view(self):
        if self.candidate_view is not None:
            self.candidate_view.clear()
            for index, candidate in enumerate(self._condition_candidates):
                item = QListWidgetItem(
                    self._condition_candidate_label(candidate)
                )
                item.setData(Qt.UserRole, index)
                item.setToolTip(
                    self._candidate_expression(candidate)
                    if candidate.get("conditions")
                    else candidate["ast"]
                )
                self.candidate_view.addItem(item)
        diagram_entries = self._condition_candidate_diagram_entries()
        if self._condition_candidates_callback is not None:
            self._condition_candidates_callback(diagram_entries)

    def _condition_candidate_diagram_entries(self):
        self._condition_candidate_occurrences = {}
        if self._function_node is None:
            return []

        entries = []
        seen_nodes = set()
        source = "\n".join(self._context.source_lines)
        for candidate in self._condition_candidates:
            matching_nodes = self._matching_candidate_nodes(candidate)
            for node in matching_nodes:
                node_source = (
                    self._statement_source_segment(node)
                    if isinstance(node, ast.stmt)
                    else ast.get_source_segment(source, node)
                )
                if node_source is None:
                    node_source = self._node_display(node, self._context)
                node_source = " ".join(node_source.split())
                line = node.lineno
                column = self._ast_column_to_utf16(
                    self._context.source_lines[line - 1],
                    getattr(node, "col_offset", 0),
                ) + 1
                label = (
                    f"{self._condition_candidate_label(candidate)} · "
                    f"{type(node).__name__} · {node_source} "
                    f"(줄 {line}, 열 {column})"
                )
                key = (id(candidate), id(node))
                if key in seen_nodes:
                    continue
                seen_nodes.add(key)
                self._condition_candidate_occurrences[label] = (
                    candidate, node
                )
                entries.append(label)
        return entries

    def _matching_candidate_nodes(self, candidate):
        statements = [
            node for node in ast.walk(self._function_node)
            if isinstance(node, ast.stmt)
            and self._node_has_source_location(node)
        ]
        conditions = self._candidate_conditions(candidate)
        expression = self._candidate_expression(candidate)
        matches = []
        for statement in statements:
            condition_values, _ = self._statement_condition_evidence(
                statement, conditions
            )
            if self._evaluate_condition_expression(
                expression, condition_values
            )[0]:
                matches.append(statement)
        return matches

    @staticmethod
    def _candidate_conditions(candidate):
        conditions = candidate.get("conditions")
        if conditions:
            return conditions
        return [{
            "node_type": candidate["node_type"],
            "ast": candidate["ast"],
            "source": candidate["source"],
            "line": candidate["line"],
        }]

    def _statement_condition_evidence(self, statement, conditions):
        statement_nodes = self._statement_condition_nodes(statement)
        evidence = [
            [
                node for node in statement_nodes
                if type(node).__name__ == condition["node_type"]
                and self._condition_feature(condition)
                == json.dumps(_ast_feature(node), ensure_ascii=False)
            ]
            for condition in conditions
        ]
        return [bool(matches) for matches in evidence], evidence

    @staticmethod
    def _condition_feature(condition):
        feature = condition.get("feature")
        if isinstance(feature, str):
            return feature
        try:
            parsed = ast.parse(condition["source"])
        except SyntaxError:
            return None
        source_node = next(
            (
                node for node in ast.walk(parsed)
                if type(node).__name__ == condition["node_type"]
            ),
            None,
        )
        if source_node is None:
            return None
        return json.dumps(_ast_feature(source_node), ensure_ascii=False)

    @staticmethod
    def _statement_condition_nodes(statement):
        nodes = [statement]
        pending = list(ast.iter_child_nodes(statement))
        while pending:
            node = pending.pop()
            if isinstance(node, ast.stmt):
                continue
            nodes.append(node)
            pending.extend(ast.iter_child_nodes(node))
        return nodes

    @staticmethod
    def _candidate_expression(candidate):
        expression = candidate.get("expression")
        if isinstance(expression, str) and expression.strip():
            return expression.strip()
        conditions = candidate.get("conditions", ())
        if not conditions:
            return "C1"
        parts = ["C1"]
        for index, condition in enumerate(conditions[1:], start=2):
            operator = condition.get("operator", "AND")
            parts.extend((operator, f"C{index}"))
        return " ".join(parts)

    @staticmethod
    def _evaluate_condition_expression(expression, values):
        tokens = []
        position = 0
        token_pattern = re.compile(
            r"C[1-9]\d*|AND\b|OR\b|NOT\b|[()]",
            re.IGNORECASE,
        )
        while position < len(expression):
            match = token_pattern.match(expression, position)
            if match is None:
                if expression[position].isspace():
                    position += 1
                    continue
                raise ValueError(
                    f"조건식에 허용되지 않는 문자가 있습니다: "
                    f"{expression[position]!r}"
                )
            token = match.group(0)
            if token[0].upper() == "C":
                index = int(token[1:]) - 1
                if index >= len(values):
                    raise ValueError(
                        f"{token} 조건 요소가 존재하지 않습니다."
                    )
                tokens.append(("CONDITION", index))
            else:
                tokens.append((token.upper(), token.upper()))
            position = match.end()

        if not tokens:
            raise ValueError("조건식을 입력하세요.")
        token_index = 0

        def parse_primary():
            nonlocal token_index
            if token_index >= len(tokens):
                raise ValueError("조건식이 예상보다 일찍 끝났습니다.")
            kind, value = tokens[token_index]
            if kind == "CONDITION":
                token_index += 1
                return bool(values[value]), {value}
            if kind == "(":
                token_index += 1
                result, referenced = parse_or()
                if token_index >= len(tokens) or tokens[token_index][0] != ")":
                    raise ValueError("조건식의 닫는 괄호가 없습니다.")
                token_index += 1
                return result, referenced
            raise ValueError("조건 요소 또는 여는 괄호가 필요합니다.")

        def parse_not():
            nonlocal token_index
            if (
                token_index < len(tokens)
                and tokens[token_index][0] == "NOT"
            ):
                token_index += 1
                result, referenced = parse_not()
                return not result, referenced
            return parse_primary()

        def parse_and():
            nonlocal token_index
            result, referenced = parse_not()
            while (
                token_index < len(tokens)
                and tokens[token_index][0] == "AND"
            ):
                token_index += 1
                right_result, right_referenced = parse_not()
                result = result and right_result
                referenced.update(right_referenced)
            return result, referenced

        def parse_or():
            nonlocal token_index
            result, referenced = parse_and()
            while (
                token_index < len(tokens)
                and tokens[token_index][0] == "OR"
            ):
                token_index += 1
                right_result, right_referenced = parse_and()
                result = result or right_result
                referenced.update(right_referenced)
            return result, referenced

        result, referenced = parse_or()
        if token_index != len(tokens):
            if tokens[token_index][0] == ")":
                raise ValueError("조건식에 짝이 맞지 않는 괄호가 있습니다.")
            raise ValueError("조건식에 연산자 또는 괄호가 필요합니다.")
        return result, referenced

    @staticmethod
    def _condition_candidate_label(candidate):
        name = candidate.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        conditions = candidate.get("conditions")
        if conditions:
            source = " / ".join(
                " ".join(condition["source"].split())
                for condition in conditions[:2]
            )
            if len(conditions) > 2:
                source += f" 외 {len(conditions) - 2}개"
            file_path = candidate.get("file_path")
            location = (
                f"{os.path.basename(file_path)}:{candidate['line']}"
                if isinstance(file_path, str) and file_path
                else f"예시 줄 {candidate['line']}"
            )
            return f"조건 {len(conditions)}개 · {source} ({location})"
        source = " ".join(candidate["source"].split())
        file_path = candidate.get("file_path")
        location = (
            f"{os.path.basename(file_path)}:{candidate['line']}"
            if isinstance(file_path, str) and file_path
            else f"예시 줄 {candidate['line']}"
        )
        return (
            f"{candidate['node_type']} · {source} ({location})"
        )

    def _add_selected_ast_candidate(self):
        if (
            self._context is None
            or self._candidate_settings_key is None
        ):
            return

        selected_nodes = [
            self._ast_nodes.get(item.data(0, Qt.UserRole))
            for item in self.ast_view.selectedItems()
        ]
        roots = [
            node for node in selected_nodes
            if self._node_has_source_location(node)
        ]
        if not roots:
            return

        nodes = []
        seen_patterns = set()
        for root in roots:
            for node in ast.walk(root):
                if not self._node_has_source_location(node):
                    continue
                pattern = ast.dump(node, include_attributes=False)
                if pattern in seen_patterns:
                    continue
                seen_patterns.add(pattern)
                nodes.append(node)

        dialog = ConditionCandidateDialog(
            nodes,
            self._context.source_lines,
            self.tabs,
            candidate_name=f"조건 후보 {len(self._condition_candidates) + 1}",
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        candidate = self._candidate_from_dialog(dialog)
        if candidate is None:
            return
        self._condition_candidates.append(candidate)
        self._save_condition_candidates()
        self._refresh_candidate_view()
        self.candidate_view.setCurrentRow(
            len(self._condition_candidates) - 1
        )
        self.tabs.setCurrentWidget(self.candidate_page)

    def _candidate_from_dialog(self, dialog, candidate=None):
        conditions = dialog.selected_conditions()
        expression = dialog.expression()
        if not conditions:
            QMessageBox.information(
                self.tabs,
                "조건 후보 구성",
                "조건 요소가 하나 이상 필요합니다.",
            )
            return None
        name = dialog.candidate_name()
        if not name:
            QMessageBox.information(
                dialog,
                "조건명 확인",
                "조건명을 입력하세요.",
            )
            return None
        edited_index = next(
            (
                index for index, existing in enumerate(
                    self._condition_candidates
                )
                if candidate is existing
            ),
            None,
        )
        if any(
            index != edited_index
            and self._condition_candidate_label(existing).casefold()
            == name.casefold()
            for index, existing in enumerate(self._condition_candidates)
        ):
            QMessageBox.information(
                dialog,
                "조건명 확인",
                "이미 사용 중인 조건명입니다. 다른 이름을 입력하세요.",
            )
            return None
        try:
            self._evaluate_condition_expression(
                expression, [True] * len(conditions)
            )
        except ValueError as error:
            QMessageBox.warning(
                dialog,
                "조건식 확인",
                str(error),
            )
            return None

        first_condition = conditions[0]
        source = " / ".join(
            condition["source"] for condition in conditions[:2]
        )
        if len(conditions) > 2:
            source += f" 외 {len(conditions) - 2}개"
        result = dict(candidate or {})
        result.update({
            "name": name,
            "node_type": first_condition["node_type"],
            "ast": first_condition["ast"],
            "source": source,
            "line": first_condition["line"],
            "file_path": (
                candidate.get("file_path")
                if candidate is not None
                else self._context.file_path
            ),
            "conditions": conditions,
            "expression": expression,
        })
        return result

    def _edit_selected_condition_candidate(self):
        item = self.candidate_view.currentItem()
        if item is None:
            return
        index = item.data(Qt.UserRole)
        candidate = self._condition_candidates[index]
        conditions = candidate.get("conditions")
        if not conditions:
            conditions = [{
                "node_type": candidate["node_type"],
                "ast": candidate["ast"],
                "source": candidate["source"],
                "line": candidate["line"],
            }]
        dialog = ConditionCandidateDialog(
            (),
            self._context.source_lines,
            self.tabs,
            conditions=conditions,
            expression=self._candidate_expression(candidate),
            candidate_name=self._condition_candidate_label(candidate),
        )
        if dialog.exec_() != QDialog.Accepted:
            return
        updated_candidate = self._candidate_from_dialog(dialog, candidate)
        if updated_candidate is None:
            return
        self._condition_candidates[index] = updated_candidate
        self._save_condition_candidates()
        self._refresh_candidate_view()
        self.candidate_view.setCurrentRow(index)

    def _edit_condition_candidate(self, item):
        self.candidate_view.setCurrentItem(item)
        self._edit_selected_condition_candidate()

    def _save_condition_candidates(self):
        self._candidate_settings.setValue(
            self._candidate_settings_key,
            json.dumps(self._condition_candidates, ensure_ascii=False),
        )
        self._candidate_settings.sync()
        if self._candidate_settings.status() != QSettings.NoError:
            QMessageBox.warning(
                self.tabs,
                "조건 후보 저장 실패",
                "조건 후보를 설정에 저장하지 못했습니다.",
            )

    def _remove_selected_condition_candidate(self):
        item = self.candidate_view.currentItem()
        if item is None:
            return
        self._condition_candidates.pop(item.data(Qt.UserRole))
        self._save_condition_candidates()
        self._refresh_candidate_view()

    def _on_condition_candidate_diagram_clicked(self, value):
        occurrence = self._condition_candidate_occurrences.get(value)
        if occurrence is None:
            QMessageBox.warning(
                self.tabs,
                "조건 후보 선택 실패",
                "선택한 다이어그램 조건 후보를 찾을 수 없습니다.",
            )
            return
        candidate, node = occurrence
        self._show_condition_candidate(candidate, node, value)

    def _condition_candidate_node(self, candidate):
        matching_nodes = self._matching_candidate_nodes(candidate)
        return matching_nodes[0] if matching_nodes else None

    def _show_condition_candidate(self, candidate, node, label=None):
        if label is None:
            label = self._condition_candidate_label(candidate)
        self.selection_label.setText(f"Rn · {label}")
        self._show_ast_nodes([node], node)
        self._highlight_ast_node_in_source(node)
        conditions = self._candidate_conditions(candidate)
        _, evidence = self._statement_condition_evidence(node, conditions)
        statement_text = self._statement_source_segment(node)
        explanation_candidate = dict(candidate)
        explanation_candidate["conditions"] = conditions
        dialog = ConditionMatchDialog(
            explanation_candidate,
            evidence,
            "\n".join(self._context.source_lines),
            statement_text,
            self.tabs,
        )
        dialog.exec_()

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
        selected_lines = set(source_lines)
        for source_line in self._related_source_lines:
            if source_line in selected_lines:
                continue
            selection = self._line_selection(source_line, "#e5e7eb")
            if selection is not None:
                selections.append(selection)

        for source_line in source_lines:
            selection = self._line_selection(source_line, "#fff0b3")
            if selection is None:
                continue
            selections.append(selection)
            block_number = source_line - self._function_start_line
            block = self.function_code_view.document().findBlockByNumber(
                block_number
            )
            if block.isValid() and first_selected_block is None:
                first_selected_block = block

        for line, start, end, category, _ in self._element_ranges:
            block_number = line - self._function_start_line
            if not 0 <= block_number < self._function_line_count:
                continue
            block = self.function_code_view.document().findBlockByNumber(
                block_number
            )
            if not block.isValid():
                continue
            cursor = QTextCursor(block)
            cursor.setPosition(block.position() + start)
            cursor.setPosition(block.position() + end, QTextCursor.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            selection.format.setForeground(QColor(CATEGORY_COLORS[category]))
            selections.append(selection)

        self.function_code_view.setExtraSelections(selections)
        if first_selected_block is not None:
            self.function_code_view.setTextCursor(
                QTextCursor(first_selected_block)
            )
            self.function_code_view.ensureCursorVisible()

    def _line_selection(self, source_line, background):
        block_number = source_line - self._function_start_line
        if not 0 <= block_number < self._function_line_count:
            return None
        block = self.function_code_view.document().findBlockByNumber(
            block_number
        )
        if not block.isValid():
            return None

        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        selection.format.setBackground(QColor(background))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        return selection

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
        self.ast_view.clear()
        self._ast_nodes = {}
        self._ast_items = {}
        self._selected_ast_node = None
        QTreeWidgetItem(self.ast_view, [message])
        if self.ast_source_view is not None:
            self.ast_source_view.clear()
            self.ast_source_view.setPlaceholderText(message)
        if self.add_candidate_button is not None:
            self.add_candidate_button.setEnabled(False)


def create_plugin():
    return SourceDetailPlugin()
