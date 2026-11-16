import os
import sys

from PyQt5.QtCore import Qt, QPointF, QRectF, QSettings, pyqtSignal
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QFrame,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api.refactor import FuncRefactor
from funcElementAnatomy import ModuleCodeAnalyzer
from funcdocs_plugins.api import FunctionContext
from funcdocs_plugins.manager import PluginManager


DEFAULT_FILE_TARGET = (
    r"C:\Users\hyunhoyang\Desktop\codes\githubcodes"
    r"\autoconstruction\components\NodeBlock.py"
)


class FuncDocsSettingsDialog(QDialog):
    def __init__(
        self, plugins, enabled_plugin_ids, plugin_errors, load_errors,
        parent=None, wrap_long_lines=True,
    ):
        super().__init__(parent)
        self.setWindowTitle("FuncDocs 설정")
        self.setMinimumWidth(360)
        self.resize(520, 600)
        self.plugin_checkboxes = {}
        self.wrap_long_lines_checkbox = QCheckBox("긴 줄 자동 줄바꿈")
        self.wrap_long_lines_checkbox.setChecked(wrap_long_lines)

        layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        contents = QWidget()
        contents_layout = QVBoxLayout(contents)
        trust_note = QLabel(
            "플러그인은 FuncDocs와 같은 권한으로 실행됩니다. "
            "신뢰하는 플러그인만 추가하세요."
        )
        trust_note.setWordWrap(True)
        contents_layout.addWidget(trust_note)

        for plugin in plugins:
            plugin_box = QGroupBox(plugin.name)
            plugin_layout = QVBoxLayout(plugin_box)
            checkbox = QCheckBox("활성화")
            checkbox.setChecked(plugin.plugin_id in enabled_plugin_ids)
            self.plugin_checkboxes[plugin.plugin_id] = checkbox

            error = plugin_errors.get(plugin.plugin_id)
            if error:
                checkbox.setChecked(False)
                checkbox.setEnabled(False)
            plugin_layout.addWidget(checkbox)

            description = QLabel(plugin.description)
            description.setObjectName("mutedLabel")
            description.setWordWrap(True)
            plugin_layout.addWidget(description)
            if error:
                error_label = QLabel(f"사용할 수 없음: {error}")
                error_label.setObjectName("errorLabel")
                error_label.setWordWrap(True)
                plugin_layout.addWidget(error_label)
            contents_layout.addWidget(plugin_box)

        if not plugins and not load_errors:
            contents_layout.addWidget(QLabel("검색된 플러그인이 없습니다."))

        errors = [
            f"{plugin_id}: {error}"
            for plugin_id, error in plugin_errors.items()
        ]
        errors.extend(
            f"{module_name}: {error}"
            for module_name, error in load_errors
        )
        if errors:
            error_box = QGroupBox("플러그인 오류")
            error_layout = QVBoxLayout(error_box)
            error_label = QLabel("\n".join(errors))
            error_label.setObjectName("errorLabel")
            error_label.setWordWrap(True)
            error_layout.addWidget(error_label)
            contents_layout.addWidget(error_box)

        contents_layout.addStretch(1)
        scroll_area.setWidget(contents)
        layout.addWidget(scroll_area, stretch=1)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        layout.addWidget(separator)

        display_group = QGroupBox("표시 설정")
        display_layout = QVBoxLayout(display_group)
        display_layout.addWidget(self.wrap_long_lines_checkbox)
        display_note = QLabel(
            "함수 코드, 선택한 줄, AST 뷰의 긴 줄 표시 방식을 설정합니다."
        )
        display_note.setObjectName("mutedLabel")
        display_note.setWordWrap(True)
        display_layout.addWidget(display_note)
        layout.addWidget(display_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def enabled_plugin_ids(self):
        return {
            plugin_id
            for plugin_id, checkbox in self.plugin_checkboxes.items()
            if checkbox.isChecked()
        }

    def wrap_long_lines_enabled(self):
        return self.wrap_long_lines_checkbox.isChecked()


class ClickableTextItem(QGraphicsTextItem):
    def __init__(self, text, category, value, click_handler):
        super().__init__(text)
        self.category = category
        self.value = value
        self.click_handler = click_handler
        self.setAcceptedMouseButtons(Qt.LeftButton)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setToolTip("원본 구문, AST 구조, 출처 위치를 표시합니다.")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.click_handler(self.category, self.value)
        super().mousePressEvent(event)


class RelationshipDiagramView(QGraphicsView):
    item_clicked = pyqtSignal(str, str)

    CATEGORY_INFO = (
        ("R1", "입력 매개변수", "함수에 전달되는 값", QColor("#2563eb")),
        ("R2", "객체 참조", "self 및 내부 객체 참조", QColor("#7c3aed")),
        ("R3", "객체 필드", "참조하는 객체의 속성", QColor("#0891b2")),
        ("R4", "데이터 접근", "키·인덱스 기반 접근", QColor("#059669")),
        ("R5", "객체 메서드", "다른 객체의 메서드 호출", QColor("#d97706")),
        ("R6", "함수·정적 요소", "일반 함수 및 정적 요소", QColor("#dc2626")),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#f7f9fc"))
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumSize(300, 240)
        self._has_diagram = False

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def zoom_in(self):
        self.scale(1.2, 1.2)

    def zoom_out(self):
        self.scale(1 / 1.2, 1 / 1.2)

    def fit_diagram(self):
        if self._has_diagram:
            self.resetTransform()
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def clear_diagram(self):
        scene = self.scene()
        scene.clear()
        message = self._add_text(
            scene, "왼쪽에서 함수나 메서드를 선택하면 관계도가 표시됩니다.",
            0, 0, 520, QFont("Malgun Gothic", 10), QColor("#64748b")
        )
        scene.setSceneRect(0, 0, 560, message.boundingRect().height() + 24)
        self._has_diagram = False

    def _add_text(
        self, scene, text, x, y, width, font, color, category_key=None
    ):
        if category_key is None:
            item = QGraphicsTextItem(text)
        else:
            item = ClickableTextItem(
                text, category_key, text, self.item_clicked.emit
            )
        item.setFont(font)
        item.setDefaultTextColor(color)
        item.setTextWidth(width)
        item.setPos(x, y)
        scene.addItem(item)
        return item

    @staticmethod
    def _add_rounded_rect(scene, x, y, width, height, pen, brush):
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, width, height), 12, 12)
        return scene.addPath(path, pen, brush)

    def _add_card(self, x, y, width, category_key, title, values, color):
        scene = self.scene()
        padding = 16
        title_item = self._add_text(
            scene, title, x + padding, y + padding, width - padding * 2,
            QFont("Malgun Gothic", 10, QFont.Bold), QColor("#172b4d")
        )
        content_y = y + padding + title_item.boundingRect().height() + 8
        if values:
            for value in values:
                marker = self._add_text(
                    scene, "•", x + padding, content_y, 14,
                    QFont("Malgun Gothic", 9), color
                )
                text_item = self._add_text(
                    scene, value, x + padding + 17, content_y,
                    width - padding * 2 - 17, QFont("Malgun Gothic", 9),
                    QColor("#334155"), category_key
                )
                content_y += max(
                    marker.boundingRect().height(),
                    text_item.boundingRect().height()
                ) + 5
        else:
            empty_item = self._add_text(
                scene, "감지된 항목 없음", x + padding, content_y,
                width - padding * 2, QFont("Malgun Gothic", 9),
                QColor("#94a3b8")
            )
            content_y += empty_item.boundingRect().height()

        height = content_y - y + padding
        card = self._add_rounded_rect(
            scene, x, y, width, height, QPen(color, 1.5),
            QBrush(QColor("#ffffff"))
        )
        card.setZValue(-1)
        return height

    def show_function(self, function_name, class_name, refactor_set):
        scene = self.scene()
        scene.clear()
        read_set = refactor_set[0]
        parameters = [
            item[1] for item in read_set.get("R1", [])
            if item[1] != "self"
        ]
        if class_name:
            parameters.insert(0, "self")
        signature = f"{function_name}({', '.join(parameters)})"
        heading = f"{class_name}.{signature}" if class_name else signature

        center_x = 520
        root_width = 480
        root_x = center_x - root_width / 2
        root_y = 32
        title_item = self._add_text(
            scene, "선택한 함수", root_x + 18, root_y + 12, root_width - 36,
            QFont("Malgun Gothic", 9), QColor("#dbeafe")
        )
        signature_item = self._add_text(
            scene, heading, root_x + 18,
            root_y + 15 + title_item.boundingRect().height(),
            root_width - 36, QFont("Consolas", 13, QFont.Bold),
            QColor("#ffffff")
        )
        root_height = (
            15 + title_item.boundingRect().height()
            + signature_item.boundingRect().height() + 15
        )
        self._add_rounded_rect(
            scene, root_x, root_y, root_width, root_height,
            QPen(QColor("#1d4ed8"), 1.5), QBrush(QColor("#2563eb"))
        ).setZValue(-1)

        card_width = 300
        gap_x = 24
        gap_y = 24
        start_x = center_x - (card_width * 3 + gap_x * 2) / 2
        first_y = root_y + root_height + 54
        row_heights = [0, 0]
        cards = []
        for index, (key, label, description, color) in enumerate(self.CATEGORY_INFO):
            row, column = divmod(index, 3)
            x = start_x + column * (card_width + gap_x)
            y = first_y + (row_heights[0] + gap_y if row else 0)
            values = list(dict.fromkeys(
                item[1] for item in read_set.get(key, [])
                if item[1] != "self"
            ))
            card_height = self._add_card(
                x, y, card_width, key,
                f"{key} · {label}  —  {description}",
                values, color
            )
            row_heights[row] = max(row_heights[row], card_height)
            cards.append((x + card_width / 2, y, color))

        root_bottom = QPointF(center_x, root_y + root_height)
        for card_x, card_y, color in cards:
            target = QPointF(card_x, card_y)
            line = scene.addLine(
                root_bottom.x(), root_bottom.y(), target.x(), target.y(),
                QPen(color, 1.5, Qt.DashLine)
            )
            line.setZValue(-2)
            direction = target - root_bottom
            length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5
            if length:
                unit = direction / length
                base = target - unit * 8
                perpendicular = QPointF(-unit.y(), unit.x()) * 4
                arrow = QPolygonF([
                    target,
                    base + perpendicular,
                    base - perpendicular,
                ])
                scene.addPolygon(arrow, QPen(color), QBrush(color)).setZValue(-1)

        total_height = first_y + sum(row_heights) + gap_y + 24
        scene.setSceneRect(0, 0, center_x * 2, total_height)
        self._has_diagram = True
        self.fit_diagram()


class FuncDocsWindow(QMainWindow):
    def __init__(self, file_target=DEFAULT_FILE_TARGET):
        super().__init__()
        self.file_target = file_target
        self.plugin_manager = PluginManager()
        self.plugins = self.plugin_manager.discover()
        self.plugin_settings = QSettings("CodeAutomaticAnalyzer", "FuncDocs")
        self.wrap_long_lines = self.plugin_settings.value(
            "ui/wrapLongLines", True, type=bool
        )
        self.plugin_enabled = {}
        for plugin in self.plugins:
            default_enabled = plugin.default_enabled
            if plugin.plugin_id == "read_write_summary":
                default_enabled = self.plugin_settings.value(
                    "plugins/read_write_summary",
                    default_enabled,
                    type=bool,
                )
            self.plugin_enabled[plugin.plugin_id] = self.plugin_settings.value(
                f"plugins/{plugin.plugin_id}/enabled",
                default_enabled,
                type=bool,
            )
        self.plugin_widgets = {}
        self.plugin_errors = {}
        self._last_context = None
        self.setWindowTitle("Function Documentation")
        self.resize(1480, 820)
        self.setMinimumSize(1100, 680)
        self._build_ui()

        self.path_input.setText(file_target)
        if self.plugin_manager.errors or self.plugin_errors:
            self.statusBar().showMessage(
                "일부 플러그인을 불러오지 못했습니다. 설정에서 오류를 확인하세요."
            )
        else:
            self.statusBar().showMessage(
                "Python 파일을 불러와 문서화할 함수를 선택하세요."
            )

    def _build_ui(self):
        central_widget = QWidget(self)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(12)

        heading = QLabel("Function Documentation")
        heading.setObjectName("heading")
        main_layout.addWidget(heading)

        path_layout = QHBoxLayout()
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("분석할 Python 파일 경로")
        self.path_input.returnPressed.connect(self.load_file)

        browse_button = QPushButton("찾아보기")
        browse_button.clicked.connect(self.browse_file)
        load_button = QPushButton("불러오기")
        load_button.setObjectName("primaryButton")
        load_button.clicked.connect(self.load_file)

        path_layout.addWidget(self.path_input, stretch=1)
        path_layout.addWidget(browse_button)
        path_layout.addWidget(load_button)
        main_layout.addLayout(path_layout)

        splitter = QSplitter(Qt.Horizontal)
        self.function_tree = QTreeWidget()
        self.function_tree.setHeaderLabel("클래스 / 함수")
        self.function_tree.setMinimumWidth(260)
        self.function_tree.currentItemChanged.connect(self.on_selection_changed)

        diagram_panel = QWidget()
        diagram_layout = QVBoxLayout(diagram_panel)
        diagram_layout.setContentsMargins(0, 0, 0, 0)
        diagram_layout.setSpacing(6)
        diagram_toolbar = QHBoxLayout()
        diagram_toolbar.addWidget(QLabel("함수 관계 다이어그램"))
        diagram_toolbar.addStretch(1)
        zoom_out_button = QPushButton("−")
        zoom_out_button.setToolTip("축소")
        zoom_out_button.clicked.connect(self._zoom_out)
        zoom_in_button = QPushButton("+")
        zoom_in_button.setToolTip("확대")
        zoom_in_button.clicked.connect(self._zoom_in)
        fit_button = QPushButton("전체 보기")
        fit_button.clicked.connect(self._fit_diagram)
        settings_button = QPushButton("도구 설정")
        settings_button.clicked.connect(self.open_settings)
        diagram_toolbar.addWidget(zoom_out_button)
        diagram_toolbar.addWidget(zoom_in_button)
        diagram_toolbar.addWidget(fit_button)
        diagram_toolbar.addWidget(settings_button)
        diagram_layout.addLayout(diagram_toolbar)
        self.diagram_view = RelationshipDiagramView()
        self.diagram_view.item_clicked.connect(
            self.on_diagram_item_clicked
        )
        self.diagram_view.clear_diagram()
        diagram_layout.addWidget(self.diagram_view, stretch=1)

        self.plugin_area = QGroupBox("분석 플러그인")
        plugin_area_layout = QVBoxLayout(self.plugin_area)
        self.plugin_tabs = QTabWidget()
        self.plugin_tabs.setDocumentMode(True)
        plugin_area_layout.addWidget(self.plugin_tabs)

        for plugin in self.plugins:
            try:
                widget = plugin.create_widget(self.plugin_area)
                if not isinstance(widget, QWidget):
                    raise TypeError("create_widget() must return QWidget")
                widget.hide()
                self.plugin_widgets[plugin.plugin_id] = widget
            except Exception as error:
                self.plugin_errors[plugin.plugin_id] = (
                    f"{type(error).__name__}: {error}"
                )
                self.plugin_enabled[plugin.plugin_id] = False
                self.plugin_settings.setValue(
                    f"plugins/{plugin.plugin_id}/enabled", False
                )
            else:
                self._set_plugin_wrap_long_lines(
                    plugin, self.wrap_long_lines
                )

        self.plugin_area.setMinimumWidth(360)
        self._refresh_plugin_tabs()

        splitter.addWidget(self.function_tree)
        splitter.addWidget(diagram_panel)
        splitter.addWidget(self.plugin_area)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([250, 770, 420])
        main_layout.addWidget(splitter, stretch=1)

        self.setCentralWidget(central_widget)
        self.setStyleSheet(
            """
            QMainWindow, QDialog {
                background: #f3f5f8;
            }
            QWidget {
                color: #243247;
                font-family: "Malgun Gothic";
                font-size: 9.5pt;
            }
            QLabel#heading {
                color: #182b49;
                font-size: 19pt;
                font-weight: 600;
            }
            QLabel#pluginSummary {
                color: #34445c;
                font-weight: 600;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #cbd4e0;
                border-radius: 5px;
                padding: 7px 12px;
            }
            QPushButton:hover {
                background: #edf2f8;
                border-color: #aab8ca;
            }
            QPushButton:pressed {
                background: #e1e9f2;
            }
            QPushButton:disabled {
                color: #91a0b3;
                background: #edf0f4;
            }
            QPushButton#primaryButton {
                background: #285f9e;
                border-color: #285f9e;
                color: white;
                font-weight: 600;
            }
            QPushButton#primaryButton:hover {
                background: #204f85;
            }
            QLineEdit, QTreeWidget, QPlainTextEdit {
                background: #ffffff;
                border: 1px solid #d3dbe6;
                border-radius: 5px;
                padding: 6px;
                selection-background-color: #d8e8fb;
                selection-color: #182b49;
            }
            QLineEdit:focus, QTreeWidget:focus, QPlainTextEdit:focus {
                border: 1px solid #6b9bd0;
            }
            QPlainTextEdit#codeView {
                color: #26364d;
                font-family: Consolas, "Malgun Gothic";
                font-size: 9pt;
                padding: 10px;
            }
            QTreeWidget {
                alternate-background-color: #f6f8fb;
                outline: 0;
            }
            QTreeWidget::item {
                padding: 4px 3px;
                border: 0;
            }
            QHeaderView::section {
                background: #eef2f7;
                color: #42536b;
                border: 0;
                border-bottom: 1px solid #d3dbe6;
                padding: 7px 6px;
                font-weight: 600;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d9e0e9;
                border-radius: 7px;
                margin-top: 12px;
                padding: 12px 9px 8px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #35465e;
            }
            QTabWidget::pane {
                background: #ffffff;
                border: 1px solid #d9e0e9;
                border-radius: 5px;
                top: -1px;
            }
            QTabBar::tab {
                background: #e9eef4;
                color: #52627a;
                border: 1px solid #d9e0e9;
                border-bottom: 0;
                border-top-left-radius: 5px;
                border-top-right-radius: 5px;
                padding: 6px 12px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #234f7c;
                font-weight: 600;
            }
            QTabBar::tab:hover:!selected {
                background: #f5f7fa;
            }
            QSplitter::handle {
                background: #e0e6ee;
            }
            QSplitter::handle:horizontal {
                width: 5px;
            }
            QSplitter::handle:vertical {
                height: 5px;
            }
            QScrollArea {
                background: transparent;
                border: 0;
            }
            QCheckBox {
                spacing: 7px;
            }
            QLabel#mutedLabel {
                color: #68788e;
                font-size: 9pt;
            }
            QLabel#errorLabel {
                color: #b42332;
            }
            QScrollBar:vertical {
                background: #f3f5f8;
                width: 10px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: #c6d0dd;
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::handle:vertical:hover {
                background: #aab8c9;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #f3f5f8;
                height: 10px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: #c6d0dd;
                border-radius: 4px;
                min-width: 24px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #aab8c9;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            """
        )

    def browse_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Python 파일 선택",
            self.path_input.text().strip() or os.getcwd(),
            "Python Files (*.py)",
        )
        if file_path:
            self.path_input.setText(file_path)
            self.load_file()

    def load_file(self):
        file_path = self.path_input.text().strip()
        if not file_path or not os.path.isfile(file_path):
            QMessageBox.warning(self, "파일 확인", "존재하는 Python 파일 경로를 입력하세요.")
            return

        analyzer = ModuleCodeAnalyzer(file_path)
        if analyzer.tree is None:
            QMessageBox.critical(
                self,
                "분석 실패",
                "파일을 읽지 못했거나 Python 구문 분석에 실패했습니다.",
            )
            return

        self.file_target = os.path.abspath(file_path)
        self.function_tree.clear()
        self.diagram_view.clear_diagram()
        self._clear_plugins()
        structure = analyzer.get_structure()

        for name, methods in structure.items():
            if name == "defs":
                for function_name in methods:
                    self._add_function_item(self.function_tree, function_name, None)
                continue

            class_item = QTreeWidgetItem(self.function_tree, [name])
            class_item.setFlags(class_item.flags() & ~Qt.ItemIsSelectable)
            for method_name in methods:
                self._add_function_item(class_item, method_name, name)
            class_item.setExpanded(True)

        self.function_tree.expandAll()
        self.statusBar().showMessage(f"불러옴: {self.file_target}")
        if not self.function_tree.topLevelItemCount():
            self.diagram_view.clear_diagram()

    @staticmethod
    def _add_function_item(parent, function_name, class_name):
        item = QTreeWidgetItem(parent, [function_name])
        item.setData(0, Qt.UserRole, (function_name[:-2], class_name))

    def on_selection_changed(self, current, _previous):
        if current is None or current is _previous:
            return

        selection = current.data(0, Qt.UserRole)
        if selection is None:
            return

        function_name, class_name = selection
        try:
            refactor = FuncRefactor()
            refactor.selectFunc(function_name, self.file_target, class_name)
            self.diagram_view.show_function(
                function_name, class_name, refactor.refactorSet
            )
            context = FunctionContext(
                self.file_target,
                function_name,
                class_name,
                refactor.refactorSet,
                refactor.refactorLocations,
                refactor.sourceLines,
            )
            self._last_context = context
            for plugin in self.plugins:
                if (
                    self.plugin_enabled.get(plugin.plugin_id, False)
                    and plugin.plugin_id in self.plugin_widgets
                ):
                    self._invoke_plugin(
                        plugin, "on_function_selected", context
                    )
            qualified_name = (
                f"{class_name}.{function_name}" if class_name else function_name
            )
            self.statusBar().showMessage(f"문서 표시 중: {qualified_name}")
        except (OSError, ValueError, KeyError) as error:
            self.diagram_view.clear_diagram()
            self._clear_plugins()
            QMessageBox.critical(self, "문서 생성 실패", str(error))

    def on_diagram_item_clicked(self, category, value):
        context = self._last_context
        if context is None:
            return

        for plugin in self.plugins:
            if (
                self.plugin_enabled.get(plugin.plugin_id, False)
                and plugin.plugin_id in self.plugin_widgets
                and callable(
                    getattr(plugin, "on_diagram_item_clicked", None)
                )
            ):
                succeeded = self._invoke_plugin(
                    plugin,
                    "on_diagram_item_clicked",
                    context,
                    category,
                    value,
                )
                if succeeded:
                    widget = self.plugin_widgets[plugin.plugin_id]
                    tab_index = self.plugin_tabs.indexOf(widget)
                    if tab_index >= 0:
                        self.plugin_tabs.setCurrentIndex(tab_index)

    def open_settings(self):
        dialog = FuncDocsSettingsDialog(
            self.plugins,
            {
                plugin_id for plugin_id, enabled in self.plugin_enabled.items()
                if enabled
            },
            self.plugin_errors,
            self.plugin_manager.errors,
            self,
            wrap_long_lines=self.wrap_long_lines,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        wrap_long_lines = dialog.wrap_long_lines_enabled()
        if wrap_long_lines != self.wrap_long_lines:
            self.wrap_long_lines = wrap_long_lines
            self.plugin_settings.setValue(
                "ui/wrapLongLines", self.wrap_long_lines
            )
            for plugin in self.plugins:
                if plugin.plugin_id in self.plugin_widgets:
                    self._set_plugin_wrap_long_lines(
                        plugin, self.wrap_long_lines
                    )

        enabled_ids = dialog.enabled_plugin_ids()
        for plugin in self.plugins:
            plugin_id = plugin.plugin_id
            enabled = (
                plugin_id in enabled_ids
                and plugin_id not in self.plugin_errors
            )
            was_enabled = self.plugin_enabled.get(plugin_id, False)
            self.plugin_enabled[plugin_id] = enabled
            self.plugin_settings.setValue(
                f"plugins/{plugin_id}/enabled", enabled
            )

            if was_enabled and not enabled:
                self._invoke_plugin(plugin, "clear")
            elif enabled and not was_enabled and self._last_context is not None:
                self._invoke_plugin(
                    plugin, "on_function_selected", self._last_context
                )
        self._refresh_plugin_tabs()

    def _clear_plugins(self):
        self._last_context = None
        for plugin in self.plugins:
            if plugin.plugin_id in self.plugin_widgets:
                self._invoke_plugin(plugin, "clear")

    def _invoke_plugin(self, plugin, method_name, *args):
        try:
            getattr(plugin, method_name)(*args)
            return True
        except Exception as error:
            plugin_id = plugin.plugin_id
            message = f"{type(error).__name__}: {error}"
            self.plugin_errors[plugin_id] = message
            self.plugin_enabled[plugin_id] = False
            self.plugin_settings.setValue(
                f"plugins/{plugin_id}/enabled", False
            )
            widget = self.plugin_widgets.get(plugin_id)
            if widget is not None:
                widget.setEnabled(False)
            self._refresh_plugin_tabs()
            QMessageBox.critical(
                self,
                "플러그인 실행 실패",
                f"{plugin.name} 플러그인에서 오류가 발생했습니다.\n{message}",
            )
            return False

    def _set_plugin_wrap_long_lines(self, plugin, enabled):
        if callable(getattr(plugin, "set_wrap_long_lines", None)):
            self._invoke_plugin(plugin, "set_wrap_long_lines", enabled)

    def _refresh_plugin_tabs(self):
        for widget in self.plugin_widgets.values():
            widget.hide()
        while self.plugin_tabs.count():
            self.plugin_tabs.removeTab(0)
        for plugin in self.plugins:
            widget = self.plugin_widgets.get(plugin.plugin_id)
            if (
                widget is not None
                and self.plugin_enabled.get(plugin.plugin_id, False)
            ):
                self.plugin_tabs.addTab(widget, plugin.name)
        self.plugin_area.setVisible(self.plugin_tabs.count() > 0)

    def _zoom_in(self):
        self.diagram_view.zoom_in()

    def _zoom_out(self):
        self.diagram_view.zoom_out()

    def _fit_diagram(self):
        self.diagram_view.fit_diagram()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FuncDocsWindow()
    window.show()
    sys.exit(app.exec_())
