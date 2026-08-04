import ast
import os
from collections import defaultdict, Counter

class ModuleCodeAnalyzer:
    """
    .py 파일 전체를 읽어 요소별 위치 추적 및 라인별 해부(every_line_view),
    위치(Scope) 중심 요약(print_summary) 및 요소(Element) 중심 요약(element_centric_summary)을 제공하는 분석기
    """
    def __init__(self, file_path: str):
        self.file_path = os.path.abspath(file_path)
        self.source_code = self._read_file_safe(self.file_path)
        
        self.lines = self.source_code.splitlines() if self.source_code else []
        self.line_elements = defaultdict(lambda: defaultdict(list))
        
        # 1. 위치 중심 요약 데이터 (Scope -> Item -> Lines)
        self.summary_data = defaultdict(lambda: defaultdict(list))
        
        # 2. 요소 중심 요약 데이터 (Category -> Item -> [(Line, Scope)])
        self.element_data = defaultdict(lambda: defaultdict(list))
        
        if self.source_code.strip():
            try:
                self.tree = ast.parse(self.source_code)
                self._add_parent_references(self.tree)
                self._parse_all_nodes()
            except SyntaxError as e:
                print(f"⚠️ [SyntaxError] 파이썬 문법 에러로 AST 분석에 실패했습니다 (Line {e.lineno}): {e.msg}")
                self.tree = None
        else:
            self.tree = None

    def _read_file_safe(self, path: str) -> str:
        """UTF-8, UTF-8-SIG, CP949, EUC-KR 순으로 호환 읽기"""
        if not os.path.exists(path):
            print(f"❌ [파일 없음] 경로를 찾을 수 없습니다: {path}")
            return ""

        encodings = ["utf-8", "utf-8-sig", "cp949", "euc-kr"]
        for enc in encodings:
            try:
                with open(path, "r", encoding=enc) as f:
                    content = f.read()
                    if content:
                        return content
            except Exception:
                continue
        
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception as e:
            print(f"❌ [읽기 오류] 파일 읽기 실패: {e}")
            return ""

    def _add_parent_references(self, tree):
        """AST 노드 상위 부모 노드 참조 추가 (Scope 추적용)"""
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child.parent = parent

    def _get_node_scope(self, node) -> str:
        """해당 노드가 속한 클래스/함수 위치 경로 추출 (예: MyClass.my_method() 또는 my_func())"""
        scopes = []
        curr = getattr(node, 'parent', None)
        
        while curr:
            if isinstance(curr, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append(f"{curr.name}()")
            elif isinstance(curr, ast.ClassDef):
                scopes.append(curr.name)
            curr = getattr(curr, 'parent', None)
            
        if not scopes:
            return "Global"
            
        return ".".join(reversed(scopes))

    def get_element_data(self):
        """요소 중심 분석 데이터를 외부 모듈에 제공"""
        return self.element_data

    def _record_element(self, category: str, item_name: str, lineno: int, scope: str):
        """두 가지 요약 데이터 구조에 모두 수집 기록"""
        # Scope 중심 구조
        self.summary_data[scope][f"{category} '{item_name}'" if category not in ["Functions", "Classes"] else item_name].append(lineno)
        # Element 중심 구조
        self.element_data[category][item_name].append((lineno, scope))

    def _parse_all_nodes(self):
        """AST 노드를 순회하며 데이터 수집"""
        for node in ast.walk(self.tree):
            lineno = getattr(node, 'lineno', None)
            if lineno is None:
                continue

            scope = self._get_node_scope(node)

            # 1. 클래스 정의
            if isinstance(node, ast.ClassDef):
                self.line_elements[lineno]["Classes"].append(f"ClassDef: {node.name}")
                self._record_element("Classes", f"class {node.name}", lineno, scope)

            # 2. 함수 및 메서드 정의
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.line_elements[lineno]["Functions"].append(f"FunctionDef: {node.name}")
                self._record_element("Functions", f"def {node.name}()", lineno, scope)

                # 파라미터
                args = node.args
                func_scope = f"{scope}.{node.name}()" if scope != "Global" else f"{node.name}()"
                
                for arg in args.args + args.kwonlyargs:
                    arg_line = getattr(arg, 'lineno', lineno)
                    self.line_elements[arg_line]["Params"].append(f"Param: {arg.arg}")
                    self._record_element("Parameter", f"{arg.arg}", arg_line, func_scope)
                if args.vararg:
                    self.line_elements[lineno]["Params"].append(f"Param: *{args.vararg.arg}")
                    self._record_element("Parameter", f"*{args.vararg.arg}", lineno, func_scope)
                if args.kwarg:
                    self.line_elements[lineno]["Params"].append(f"Param: **{args.kwarg.arg}")
                    self._record_element("Parameter", f"**{args.kwarg.arg}", lineno, func_scope)

            # 3. 변수 할당
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.line_elements[lineno]["Vars"].append(f"Var: {target.id}")
                        self._record_element("Variable", f"{target.id}", lineno, scope)
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    self.line_elements[lineno]["Vars"].append(f"Var: {node.target.id}")
                    self._record_element("Variable", f"{node.target.id}", lineno, scope)

            # 4. 함수 및 메서드 호출
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    self.line_elements[lineno]["Calls"].append(f"CallFunc: {node.func.id}()")
                    self._record_element("Function", f"{node.func.id}()", lineno, scope)
                elif isinstance(node.func, ast.Attribute):
                    obj_name = ast.unparse(node.func.value)
                    method_name = f".{node.func.attr}()"
                    full_method_str = f"[{obj_name}]{method_name}"

                    self.line_elements[lineno]["Methods"].append(f"CallMethod: [{obj_name}]{method_name}")
                    self._record_element("Called Methods", full_method_str, lineno, scope)

            # 5. 리턴 문
            elif isinstance(node, ast.Return):
                val = ast.unparse(node.value) if node.value else "None"
                self.line_elements[lineno]["Returns"].append(f"Return: {val}")
                self._record_element("Return", f"return {val}", lineno, scope)

            # 6. 예외 처리
            elif isinstance(node, ast.Raise):
                exc_str = ast.unparse(node.exc) if node.exc else "Re-raise"
                self.line_elements[lineno]["Raises"].append(f"Raise: {exc_str}")
                self._record_element("Exception Raised", f"raise {exc_str}", lineno, scope)
                
            elif isinstance(node, ast.ExceptHandler):
                exc_type = ast.unparse(node.type) if node.type else "Bare except"
                self.line_elements[lineno]["Excepts"].append(f"Except: {exc_type}")
                self._record_element("Exceptions Handled", f"except {exc_type}", lineno, scope)

    def scope_centric_summary(self):
        """[Scope 중심] 소속 위치(함수/클래스)를 Key로 그룹화하여 사용된 라인 번호 리스트 출력"""
        print(f"\n================================================================================")
        print(f" 📊 [Summary Analysis - Scope Centric] File: {self.file_path}")
        print(f"================================================================================")
        
        if not self.summary_data:
            print("  분석할 데이터가 없습니다.")
            return

        sorted_scopes = sorted(self.summary_data.keys(), key=lambda s: (s != "Global", s))

        for scope in sorted_scopes:
            item_dict = self.summary_data[scope]
            print(f"\n📌 [{scope} 위치]:")
            
            for item_name, lines in sorted(item_dict.items()):
                unique_lines = sorted(list(set(lines)))
                lines_str = ", ".join(map(str, unique_lines))
                print(f"   • {item_name} (Line {lines_str})")
                
        print(f"================================================================================")

    def element_centric_summary(self):
        """[요소 중심] 카테고리/항목별로 어느 위치(Scope)에서 몇 번 라인에 사용되었는지 출력"""
        print(f"\n================================================================================")
        print(f" 📊 [Summary Analysis - Element Centric] File: {self.file_path}")
        print(f"================================================================================")
        
        if not self.element_data:
            print("  분석할 데이터가 없습니다.")
            return

        for category, item_dict in self.element_data.items():
            print(f"\n📌 {category} ({len(item_dict)}종류):")
            for item_name, line_scope_list in sorted(item_dict.items()):
                # Scope별로 라인 번호 묶기 {Scope: [Lines]}
                scope_lines = defaultdict(list)
                for line, scope in line_scope_list:
                    scope_lines[scope].append(line)
                
                # 라인 오름차순 정렬 후 포맷팅
                formatted_parts = []
                for scope in sorted(scope_lines.keys(), key=lambda s: (s != "Global", s)):
                    lines = sorted(list(set(scope_lines[scope])))
                    lines_str = ", ".join(map(str, lines))
                    formatted_parts.append(f"Line {lines_str} : {scope} 위치")
                
                pos_formatted = " | ".join(formatted_parts)
                print(f"   • {item_name} \n\t({pos_formatted})")
                
        print(f"================================================================================")

    def every_line_view(self):
        """소스코드 전체를 라인별 원문 + 하나로 묶인 요소를 해부하여 출력"""
        print(f"\n================================================================================")
        print(f" 📄 [Every Line View] File: {self.file_path}")
        print(f"================================================================================")
        
        if not self.lines:
            print("  (빈 파일이거나 내용을 읽을 수 없습니다.)")
            print(f"================================================================================")
            return

        for idx, line_content in enumerate(self.lines, start=1):
            elements = self.line_elements[idx]
            
            found_list = []
            for category, items in elements.items():
                if items:
                    counts = Counter(items)
                    formatted_items = []
                    for item, count in sorted(counts.items()):
                        if count > 1:
                            formatted_items.append(f"{item} (x{count})")
                        else:
                            formatted_items.append(item)
                    
                    found_list.append(f"[{', '.join(formatted_items)}]")

            line_str = f"Line {idx:3d} | {line_content}"
            
            if found_list:
                info_str = " ".join(found_list)
                print(f"{line_str:<70} 💡 {info_str}")
            else:
                print(f"{line_str}")
        
        print(f"================================================================================")


# ==========================================
# 🚀 실행부
# ==========================================
if __name__ == "__main__":
    file_target = r"E:\autoconstruction\components\Edit.py"
    
    analyzer = ModuleCodeAnalyzer(file_target)
    analyzer.scope_centric_summary()
