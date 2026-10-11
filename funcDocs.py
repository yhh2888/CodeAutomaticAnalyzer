import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
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

        self.doc_view = QTextEdit()
        self.doc_view.setReadOnly(True)
        self.doc_view.setPlaceholderText("왼쪽에서 함수나 메서드를 선택하면 문서가 표시됩니다.")
        self.doc_view.setFont(QFont("Consolas", 10))

        splitter.addWidget(self.function_tree)
        splitter.addWidget(self.doc_view)
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
        self.doc_view.clear()
        self.statusBar().showMessage(f"불러옴: {self.file_target}")
        if not self.function_tree.topLevelItemCount():
            self.doc_view.setPlainText("이 파일에서 클래스나 함수를 찾지 못했습니다.")

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
            self.doc_view.setPlainText(
                refactor.docMaker(isMethod=class_name is not None)
            )
            qualified_name = (
                f"{class_name}.{function_name}" if class_name else function_name
            )
            self.statusBar().showMessage(f"문서 표시 중: {qualified_name}")
        except (OSError, ValueError, KeyError) as error:
            self.doc_view.clear()
            QMessageBox.critical(self, "문서 생성 실패", str(error))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FuncDocsWindow()
    window.show()
    sys.exit(app.exec_())
