import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QSplitter, QTextEdit
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor

# 제공해주신 모듈 Import (동일 경로 또는 Python Path 등록 필요)
from funcElementAnatomy import ModuleCodeAnalyzer
from funcOrigin import FuncOrigin  # 파일명에 맞춰 변경해주세요
from funcInfluence import FuncInfluenceAnalyzer  # 파일명에 맞춰 변경해주세요


class CodeAnalysisDashboard(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🐍 Python Static Code Analysis Dashboard")
        self.setGeometry(100, 100, 1400, 850)
        
        self.file_path = ""
        self.init_ui()

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        # -----------------------------------------------------------------
        # 1. 상단 파일 컨트롤 파트
        # -----------------------------------------------------------------
        top_bar = QHBoxLayout()
        self.lbl_file = QLabel("📁 분석할 파일: 선택되지 않음")
        self.lbl_file.setFont(QFont("Malgun Gothic", 10, QFont.Bold))
        
        btn_open = QPushButton("파일 열기 (.py)")
        btn_open.clicked.connect(self.open_file)
        
        btn_run = QPushButton("🚀 통합 분석 실행")
        btn_run.setStyleSheet("background-color: #2b5b84; color: white; font-weight: bold;")
        btn_run.clicked.connect(self.run_analysis)

        top_bar.addWidget(self.lbl_file, stretch=1)
        top_bar.addWidget(btn_open)
        top_bar.addWidget(btn_run)
        main_layout.addLayout(top_bar)

        # -----------------------------------------------------------------
        # 2. 메인 분석 결과 탭 구성
        # -----------------------------------------------------------------
        self.tabs = QTabWidget()
        
        # Tab 1: Module Anatomy (요소 구조 & Every Line View)
        self.tab_anatomy = QWidget()
        self.setup_anatomy_tab()
        self.tabs.addTab(self.tab_anatomy, "1. Code Anatomy")

        # Tab 2: FuncOrigin (생성/정의 출처)
        self.tab_origin = QWidget()
        self.setup_origin_tab()
        self.tabs.addTab(self.tab_origin, "2. Element Origin")

        # Tab 3: FuncInfluence (Side-Effects & Risks)
        self.tab_influence = QWidget()
        self.setup_influence_tab()
        self.tabs.addTab(self.tab_influence, "3. Side-Effects & Risks")

        main_layout.addWidget(self.tabs)

    # =====================================================================
    # TAB 1 SETUP: Code Anatomy
    # =====================================================================
    def setup_anatomy_tab(self):
        layout = QHBoxLayout(self.tab_anatomy)
        splitter = QSplitter(Qt.Horizontal)

        # 왼쪽: Scope/Element 트라이 뷰
        self.tree_anatomy = QTreeWidget()
        self.tree_anatomy.setHeaderLabels(["분류 / Scope / Element", "라인 정보"])
        self.tree_anatomy.header().setSectionResizeMode(0, QHeaderView.Stretch)
        
        # 오른쪽: Every Line View (소스코드 + AST 태깅)
        self.txt_line_view = QTextEdit()
        self.txt_line_view.setFont(QFont("Consolas", 10))
        self.txt_line_view.setReadOnly(True)

        splitter.addWidget(self.tree_anatomy)
        splitter.addWidget(self.txt_line_view)
        splitter.setSizes([500, 900])
        layout.addWidget(splitter)

    # =====================================================================
    # TAB 2 SETUP: Element Origin
    # =====================================================================
    def setup_origin_tab(self):
        layout = QVBoxLayout(self.tab_origin)
        self.table_origin = QTableWidget()
        self.table_origin.setColumnCount(3)
        self.table_origin.setHorizontalHeaderLabels(["카테고리 (Category)", "요소 이름 (Element)", "생성 / 정의 출처 (Origin)"])
        self.table_origin.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_origin.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_origin.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table_origin)

    # =====================================================================
    # TAB 3 SETUP: Side-Effects & Risks (Influence)
    # =====================================================================
    def setup_influence_tab(self):
        layout = QVBoxLayout(self.tab_influence)
        self.tree_influence = QTreeWidget()
        self.tree_influence.setHeaderLabels(["함수명 / 분석 항목", "Line", "세부 정보 및 표현식"])
        self.tree_influence.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree_influence.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree_influence.header().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.tree_influence)

    # =====================================================================
    # LOGIC: 파일 탐색 및 통합 분석 데이터 매핑
    # =====================================================================
    def open_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "파이썬 파일 선택", "", "Python Files (*.py)")
        if file_path:
            self.file_path = file_path
            self.lbl_file.setText(f"📁 분석할 파일: {file_path}")

    def run_analysis(self):
        if not self.file_path or not os.path.exists(self.file_path):
            self.lbl_file.setText("❌ 올바른 파일 경로를 선택해주세요!")
            return

        # 1. 모듈 객체 생성 및 분석 실행
        anatomy_analyzer = ModuleCodeAnalyzer(self.file_path)
        origin_analyzer = FuncOrigin(anatomy_analyzer)
        
        influence_analyzer = None
        if anatomy_analyzer.tree:
            influence_analyzer = FuncInfluenceAnalyzer(anatomy_analyzer.tree)
            influence_analyzer.analyze()

        # 2. UI 데이터 업데이트
        self.populate_anatomy_tab(anatomy_analyzer)
        self.populate_origin_tab(origin_analyzer)
        if influence_analyzer:
            self.populate_influence_tab(influence_analyzer)

    # -----------------------------------------------------------------
    # UI Population 1: Module Anatomy
    # -----------------------------------------------------------------
    def populate_anatomy_tab(self, analyzer: ModuleCodeAnalyzer):
        self.tree_anatomy.clear()
        
        # 1-A. Element Centric Tree
        root_element = QTreeWidgetItem(self.tree_anatomy, ["📌 [Element Centric Summary]"])
        for category, item_dict in analyzer.element_data.items():
            cat_node = QTreeWidgetItem(root_element, [f"{category} ({len(item_dict)})"])
            for item_name, line_scope_list in item_dict.items():
                item_node = QTreeWidgetItem(cat_node, [item_name])
                for line, scope in line_scope_list:
                    QTreeWidgetItem(item_node, [f"Scope: {scope}", f"Line {line}"])
        
        root_element.setExpanded(True)

        # 1-B. Every Line View Text Box
        self.txt_line_view.clear()
        line_text_html = []
        for idx, line_content in enumerate(analyzer.lines, start=1):
            elements = analyzer.line_elements[idx]
            found_list = []
            for category, items in elements.items():
                if items:
                    found_list.append(f"<b>[{category}: {', '.join(set(items))}]</b>")

            line_str = f"<span style='color:gray;'>{idx:4d} |</span> {line_content}"
            if found_list:
                line_str += f"  <span style='color:#007acc;'>💡 {' '.join(found_list)}</span>"
            
            line_text_html.append(line_str)

        self.txt_line_view.setHtml("<br>".join(line_text_html))

    # -----------------------------------------------------------------
    # UI Population 2: FuncOrigin
    # -----------------------------------------------------------------
    def populate_origin_tab(self, origin_analyzer: FuncOrigin):
        self.table_origin.setRowCount(0)
        
        row_idx = 0
        for category, items in origin_analyzer.categorized_origins.items():
            for name, origin_desc in sorted(items.items()):
                self.table_origin.insertRow(row_idx)
                
                item_cat = QTableWidgetItem(category)
                item_name = QTableWidgetItem(name)
                item_origin = QTableWidgetItem(origin_desc)

                # 스타일링
                item_cat.setForeground(QColor("#2b5b84"))
                
                self.table_origin.setItem(row_idx, 0, item_cat)
                self.table_origin.setItem(row_idx, 1, item_name)
                self.table_origin.setItem(row_idx, 2, item_origin)
                row_idx += 1

    # -----------------------------------------------------------------
    # UI Population 3: FuncInfluence
    # -----------------------------------------------------------------
    def populate_influence_tab(self, influence_analyzer: FuncInfluenceAnalyzer):
        self.tree_influence.clear()

        for func_name, info in influence_analyzer.influence_data.items():
            func_node = QTreeWidgetItem(self.tree_influence, [f"🔹 함수: [{func_name}()]"])
            func_node.setFont(0, QFont("Malgun Gothic", 10, QFont.Bold))

            # 1. 파라미터 상태 요약
            if info["params_summary"]:
                param_node = QTreeWidgetItem(func_node, ["📌 파라미터 상태 요약"])
                for p_name, p_state in info["params_summary"].items():
                    status = []
                    if p_state["mutated"]: status.append("⚠️ 외부 메모리 직접 수정됨 (Mutated)")
                    if p_state["rebound"]: status.append("ℹ️ 내부 참조 재할당됨 (Rebound)")
                    if not status: status.append("✅ 변경 없음 (Pure)")
                    QTreeWidgetItem(param_node, [f"• {p_name}", "", ", ".join(status)])

            # 2. 실제 변형 발생 (Actual Side-Effects)
            if info["actual_param_mutations"]:
                mut_node = QTreeWidgetItem(func_node, ["🔥 [실제 변형] 파라미터 In-place 수정"])
                for item in info["actual_param_mutations"]:
                    QTreeWidgetItem(mut_node, [f"• {item['param']}", f"Line {item['line']}", f"{item.get('type', '')} -> {item['expr']}"])

            if info["actual_global_mutations"] or info["global_obj_mutations"]:
                glob_node = QTreeWidgetItem(func_node, ["🌍 [Scope 변형] Global / Scope 변경"])
                for item in info["actual_global_mutations"]:
                    QTreeWidgetItem(glob_node, [f"• {item['var']}", f"Line {item['line']}", item['type']])
                for item in info["global_obj_mutations"]:
                    QTreeWidgetItem(glob_node, [f"• {item['target']}", f"Line {item['line']}", f"Global 객체 수정: {item['expr']}"])

            # 3. 잠재적 위험 (Potential Risks)
            has_potential = any([
                info["mutable_default_args"], info["escaped_params_to_calls"],
                info["escaped_params_to_globals"], info["returned_param_aliases"],
                info["shallow_copy_risks"]
            ])

            if has_potential:
                risk_node = QTreeWidgetItem(func_node, ["⚠️ [잠재적 위험] 외부 유출 및 변형 가능성"])
                for item in info["mutable_default_args"]:
                    QTreeWidgetItem(risk_node, ["• 가변 기본값", f"Line {item['line']}", item['desc']])
                for item in info["escaped_params_to_calls"]:
                    QTreeWidgetItem(risk_node, [f"• 외부 함수 유출 ({item['param']})", f"Line {item['line']}", f"파라미터가 '{item['called_func']}()' 인자로 전달됨"])
                for item in info["escaped_params_to_globals"]:
                    QTreeWidgetItem(risk_node, [f"• Global 유출 ({item['param']})", f"Line {item['line']}", f"global '{item['global_var']}'에 할당됨"])
                for item in info["returned_param_aliases"]:
                    QTreeWidgetItem(risk_node, [f"• Return 유출 ({item['param']})", f"Line {item['line']}", "파라미터 참조가 그대로 반환됨"])

            # 4. 반환 정보
            if info["returns"]:
                ret_node = QTreeWidgetItem(func_node, ["📤 [반환 정보]"])
                for item in info["returns"]:
                    QTreeWidgetItem(ret_node, ["• return", f"Line {item['line']}", item['value']])

            func_node.setExpanded(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    dashboard = CodeAnalysisDashboard()
    dashboard.show()
    sys.exit(app.exec_())
