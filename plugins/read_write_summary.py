from PyQt5.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from funcdocs_plugins.api import FuncDocsPlugin, FunctionContext


class ReadWriteSummaryPlugin(FuncDocsPlugin):
    plugin_id = "read_write_summary"
    name = "읽기/쓰기 요약"
    description = "선택한 함수에서 감지한 읽기·쓰기 항목을 표시합니다."
    default_enabled = True
    order = 20

    READ_CATEGORIES = (
        ("R1", "매개변수"),
        ("R2", "객체 참조"),
        ("R3", "객체 필드"),
        ("R4", "키·인덱스 접근"),
        ("R5", "객체 메서드"),
        ("R6", "함수·정적 요소"),
        ("Not In R", "분류되지 않음"),
    )
    WRITE_CATEGORIES = (
        ("W1", "매개변수 변경"),
        ("W2", "분류 미구현"),
        ("W3", "분류 미구현"),
        ("W4", "분류 미구현"),
        ("W5", "분류 미구현"),
        ("W6", "반환·정적 요소"),
        ("Not In W", "분류되지 않음"),
    )

    def __init__(self):
        self.widget = None
        self.tree = None

    def create_widget(self, parent):
        self.widget = QWidget(parent)
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(8, 8, 8, 8)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["방향", "분류", "종류", "항목"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 60)
        self.tree.setColumnWidth(1, 150)
        self.tree.setColumnWidth(2, 100)
        self.tree.header().setStretchLastSection(True)
        layout.addWidget(self.tree)

        note = QLabel(
            "AST 정적 분석 결과입니다. 일부 쓰기 항목은 분류되지 않을 수 있습니다."
        )
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        self.clear()
        return self.widget

    def on_function_selected(self, context: FunctionContext):
        self.tree.clear()
        read_set, write_set = context.refactor_set
        for direction, categorized, categories in (
            ("읽기", read_set, self.READ_CATEGORIES),
            ("쓰기", write_set, self.WRITE_CATEGORIES),
        ):
            for key, label in categories:
                for type_info, expression in categorized.get(key, []):
                    QTreeWidgetItem(self.tree, [
                        direction, f"{key} · {label}", str(type_info),
                        str(expression),
                    ])

        if not self.tree.topLevelItemCount():
            self.clear("감지된 읽기/쓰기 항목이 없습니다.")

    def clear(self, message="함수를 선택하면 읽기/쓰기 결과가 표시됩니다."):
        if self.tree is None:
            return
        self.tree.clear()
        QTreeWidgetItem(self.tree, ["", "", "", message])


def create_plugin():
    return ReadWriteSummaryPlugin()
