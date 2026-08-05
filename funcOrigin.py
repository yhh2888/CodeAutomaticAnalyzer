import ast, os
from collections import defaultdict

from funcElementAnatomy import ModuleCodeAnalyzer


class FuncOrigin:
    """
    ModuleCodeAnalyzer(FuncElementAnatomy)의 수집 데이터를 받아서
    요소별(Import, 클래스, 함수, 변수, 호출 메서드 등) 최초 생성/정의 출처(Origin)를 추적하는 모듈
    """
    def __init__(self, analyzer: ModuleCodeAnalyzer):
        self.analyzer = analyzer
        self.file_path = analyzer.file_path
        self.tree = analyzer.tree
        self.element_data = analyzer.get_element_data()
        
        # { Category: { ElementName: OriginInfo } }
        self.categorized_origins = defaultdict(dict)
        self.origins = {}
        
        # 내부 클래스 메서드 위치 매핑용 { "ClassName.method_name": line_number }
        self.local_class_methods = {}
        
        if self.tree:
            self._trace_all_origins()

    def _record_origin(self, category: str, name: str, origin_info: str):
        """출처 정보 기록"""
        self.origins[name] = origin_info
        self.categorized_origins[category][name] = origin_info

    def _trace_all_origins(self):
        """ModuleCodeAnalyzer의 결과 및 AST를 바탕으로 생성/정의 출처(Origin) 추적"""
        
        # 1. AST에서 Import 출처 및 내부 클래스 메서드 수집
        for node in ast.walk(self.tree):
            lineno = getattr(node, 'lineno', '?')
            
            # (1) Import 출처 수집
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_name = alias.asname if alias.asname else alias.name
                    info = f"Imported from '{alias.name}' (Line {lineno})"
                    self._record_origin("Imports/Modules", imported_name, info)

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module if node.module else ""
                for alias in node.names:
                    imported_name = alias.asname if alias.asname else alias.name
                    info = f"Imported from '{module_name}.{alias.name}' (Line {lineno})"
                    self._record_origin("Imports/Modules", imported_name, info)

            # (2) 내부 클래스의 메서드 정의 위치 매핑
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        self.local_class_methods[f"{node.name}.{item.name}"] = getattr(item, 'lineno', '?')

        # 2. ModuleCodeAnalyzer에서 추출한 element_data를 활용해 출처 계산
        for category, item_dict in self.element_data.items():
            for item_name, line_scope_list in item_dict.items():
                if not line_scope_list:
                    continue
                
                # 가장 처음 등장/생성된 라인과 위치(Scope)
                first_line, first_scope = line_scope_list[0]

                # (1) Classes
                if category == "Classes":
                    info = f"Defined locally at Line {first_line} [{first_scope} 위치]"
                    self._record_origin("Classes", item_name, info)

                # (2) Functions / Methods
                elif category == "Functions":
                    info = f"Created locally at Line {first_line} [{first_scope} 위치]"
                    self._record_origin("Functions", item_name, info)

                # (3) Parameters
                elif category == "Parameter":
                    info = f"Created at Line {first_line} [{first_scope} 위치]"
                    self._record_origin("Parameters", f"Param '{item_name}'", info)

                # (4) Variables (최초 할당 위치)
                elif category == "Variable":
                    var_key = f"Var '{item_name}'"
                    if var_key not in self.categorized_origins["Variables"]:
                        info = f"Created locally at Line {first_line} [{first_scope} 위치]"
                        self._record_origin("Variables", var_key, info)

                # (5) Called Methods (추출 대상 객체별 출처 분석)
                elif category == "Called Methods":
                    # 예: item_name -> "[dialog].exec_()"
                    if item_name.startswith("[") and "]" in item_name:
                        obj_name = item_name[1:item_name.find("]")]
                        method_name = item_name[item_name.find("]")+1:] # .exec_()

                        # Case A: self.method() 호출
                        if obj_name == "self":
                            class_name = first_scope.split('.')[0] if first_scope != "Global" else ""
                            method_bare = method_name.strip("().")
                            method_lookup = f"{class_name}.{method_bare}"
                            
                            if method_lookup in self.local_class_methods:
                                def_line = self.local_class_methods[method_lookup]
                                info = f"Defined in class '{class_name}' at Line {def_line}"
                            else:
                                info = f"Internal method call of '{class_name}'"

                        # Case B: Import된 모듈/객체의 메서드 호출
                        elif obj_name in self.origins:
                            import_origin = self.origins[obj_name]
                            info = f"Method of [{obj_name}] -> {import_origin}"

                        # Case C: 외부/내부 일반 변수 객체의 메서드 호출
                        else:
                            info = f"Called on object '{obj_name}' (First used at Line {first_line})"

                        self._record_origin("Called Methods", f"'{obj_name}{method_name}'", info)

    def print_origin_summary(self):
        """요소별 생성/정의 출처 위치 요약 출력"""
        print(f"\n================================================================================")
        print(f" 🔍 [FuncOrigin Analysis] File: {self.file_path}")
        print(f"================================================================================")

        if not self.categorized_origins:
            print("  분석된 출처 정보가 없습니다.")
            return

        for category, items in self.categorized_origins.items():
            print(f"\n📌 {category} ({len(items)}종류):")
            for name, origin in sorted(items.items()):
                print(f"   • {name:<35} ➔ {origin}")

        print(f"================================================================================")

    def get_origin_of(self, element_name: str) -> str:
        """단건 출처 조회 API"""
        for name, origin in self.origins.items():
            if element_name == name or element_name in name:
                return origin
        return "Unknown / Built-in / Local Variable Method"


# ==========================================
# 🚀 연동 실행 테스트
# ==========================================
if __name__ == "__main__":
    file_target = r"E:\autoconstruction\components\Edit.py"
    file_target = r"C:\Users\DW\Desktop\funcAnalysis\funcImportTracker.py"
    
    # 1. FuncElementAnatomy 분석 진행
    anatomy_analyzer = ModuleCodeAnalyzer(file_target)
    
    # 2. FuncOrigin에 anatomy 분석 결과 객체를 넘겨 연동 실행
    origin_analyzer = FuncOrigin(anatomy_analyzer)
    
    # 3. 출처 요약 출력
    origin_analyzer.print_origin_summary()
