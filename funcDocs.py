import os
import sys

from PyQt5.QtCore import Qt, QPointF, QRectF
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QFrame,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api.refactor import FuncRefactor
from funcElementAnatomy import ModuleCodeAnalyzer


DEFAULT_FILE_TARGET = (
    r"C:\Users\hyunhoyang\Desktop\codes\githubcodes"
    r"\autoconstruction\components\NodeBlock.py"
)


class RelationshipDiagramView(QGraphicsView):
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

    @staticmethod
    def _add_text(scene, text, x, y, width, font, color):
        item = QGraphicsTextItem(text)
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

    def _add_card(self, x, y, width, title, values, color):
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
                    QColor("#334155")
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
                x, y, card_width, f"{key} · {label}  —  {description}",
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
        self.setWindowTitle("Function Documentation")
        self.resize(1180, 760)
        self._build_ui()

        self.path_input.setText(file_target)
        self.statusBar().showMessage("Python 파일을 불러와 문서화할 함수를 선택하세요.")

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
        diagram_toolbar.addWidget(zoom_out_button)
        diagram_toolbar.addWidget(zoom_in_button)
        diagram_toolbar.addWidget(fit_button)
        diagram_layout.addLayout(diagram_toolbar)
        self.diagram_view = RelationshipDiagramView()
        self.diagram_view.clear_diagram()
        diagram_layout.addWidget(self.diagram_view, stretch=1)

        splitter.addWidget(self.function_tree)
        splitter.addWidget(diagram_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([320, 860])
        main_layout.addWidget(splitter, stretch=1)

        self.setCentralWidget(central_widget)
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #f4f6f8;
                color: #202833;
                font-family: "Malgun Gothic";
                font-size: 10pt;
            }
            QLabel#heading {
                color: #172b4d;
                font-size: 20pt;
                font-weight: 600;
            }
            QLineEdit, QTreeWidget, QTextEdit {
                background: #ffffff;
                border: 1px solid #d5dce5;
                border-radius: 6px;
                padding: 8px;
                selection-background-color: #cfe2ff;
            }
            QPushButton {
                background: #e8edf3;
                border: 1px solid #d5dce5;
                border-radius: 6px;
                padding: 8px 14px;
            }
            QPushButton:hover {
                background: #dce5ef;
            }
            QPushButton#primaryButton {
                background: #2864a5;
                border-color: #2864a5;
                color: white;
                font-weight: 600;
            }
            QPushButton#primaryButton:hover {
                background: #1f528b;
            }
            QTreeWidget::item {
                padding: 5px;
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
            qualified_name = (
                f"{class_name}.{function_name}" if class_name else function_name
            )
            self.statusBar().showMessage(f"문서 표시 중: {qualified_name}")
        except (OSError, ValueError, KeyError) as error:
            self.diagram_view.clear_diagram()
            QMessageBox.critical(self, "문서 생성 실패", str(error))

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
