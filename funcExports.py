import ast
from collections import defaultdict
from pathlib import Path


class FuncExport:

    def __init__(self, target_dir: str | Path):
        """
        :param target_dir: 분석할 최상위 디렉토리 경로
        """
        self.target_dir = Path(target_dir)
        self.python_files = self._get_all_python_files()

        self.ast_trees = {}
        self.module_names = {}

        # 폴더 내 모든 파일 파싱 및 스코프 부모 설정
        self._build_ast_trees()

    def _get_all_python_files(self):
        """대상 디렉토리 하위의 모든 .py 파일 경로 수집"""
        if not self.target_dir.exists():
            print(f"❌ 경로를 찾을 수 없습니다: {self.target_dir}")
            return []
        return list(self.target_dir.rglob("*.py"))

    def _build_ast_trees(self):
        """수집된 모든 .py 파일의 AST를 생성하고 Parent 참조 연결"""
        for file_path in self.python_files:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                tree = ast.parse(content)

                # Parent 참조 추가
                for parent in ast.walk(tree):
                    for child in ast.iter_child_nodes(parent):
                        child.parent = parent

                self.ast_trees[file_path] = tree
                self.module_names[file_path] = file_path.stem
            except Exception as e:
                print(f"⚠️ 파일 파싱 실패 ({file_path.name}): {e}")

    def _get_scope_path(self, node) -> str:
        """[검토 1] 해당 노드가 위치한 스코프 경로 추적 (클래스 -> 함수 -> 메서드...)"""
        scopes = []
        curr = getattr(node, "parent", None)

        while curr:
            if isinstance(curr, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes.append(f"{curr.name}()")
            elif isinstance(curr, ast.ClassDef):
                scopes.append(curr.name)
            curr = getattr(curr, "parent", None)

        return " -> ".join(reversed(scopes)) if scopes else "Global (모듈 최상위)"

    def analyze_element(self, target_name: str) -> dict:
        """특정 대상(함수, 메서드, 어트리뷰트 등)이 폴더 내 전체 파일에서

        어떻게 속해있고, 외부/로컬에서 호출/참조되는지 검토
        """
        result = {
            "target_element": target_name,
            "1_defined_locations": [],  # 1. 대상이 속한 위치 (클래스/함수/메서드 스코프)
            "2_external_calls": [],  # 2. 타 모듈(다른 파일)에서의 호출 및 참조
            "3_local_calls": [],  # 3. 로컬 모듈(동일 파일)에서의 호출 및 참조
        }

        defined_files = set()

        # -------------------------------------------------------------
        # 1. 정의 및 선언 위치 검토 (함수, 메서드, 클래스, 어트리뷰트/변수)
        # -------------------------------------------------------------
        for file_path, tree in self.ast_trees.items():
            for node in ast.walk(tree):
                is_target_def = False
                def_type = ""

                # ① 함수/메서드 정의
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == target_name
                ):
                    is_target_def = True
                    def_type = "Function/Method"

                # ② 클래스 정의
                elif isinstance(node, ast.ClassDef) and node.name == target_name:
                    is_target_def = True
                    def_type = "Class"

                # ③ 어트리뷰트/변수 할당 (self.attr = ... 또는 attr = ...)
                elif isinstance(
                    node, (ast.Assign, ast.AnnAssign, ast.AugAssign)
                ):
                    targets = (
                        node.targets
                        if isinstance(node, ast.Assign)
                        else [node.target]
                    )
                    for t in targets:
                        if isinstance(t, ast.Name) and t.id == target_name:
                            is_target_def = True
                            def_type = "Variable"
                        elif (
                            isinstance(t, ast.Attribute)
                            and t.attr == target_name
                        ):
                            is_target_def = True
                            def_type = "Attribute"

                if is_target_def:
                    defined_files.add(file_path)
                    scope_info = self._get_scope_path(node)
                    result["1_defined_locations"].append({
                        "file": str(file_path),
                        "line": getattr(node, "lineno", 0),
                        "type": def_type,
                        "belongs_to_scope": scope_info,  # 속해 있는 클래스/메서드/함수
                    })

        # -------------------------------------------------------------
        # 2 & 3. 호출 및 참조 검토 (Call, AttributeAccess, Name)
        # -------------------------------------------------------------
        for file_path, tree in self.ast_trees.items():
            mod_name = self.module_names[file_path]

            for node in ast.walk(tree):
                accessed_name = None
                action_type = "Reference"  # 단순 참조 or 호출

                # ① 함수/메서드 호출: target() 또는 obj.target()
                if isinstance(node, ast.Call):
                    if (
                        isinstance(node.func, ast.Name)
                        and node.func.id == target_name
                    ):
                        accessed_name = node.func.id
                        action_type = "Call"
                    elif (
                        isinstance(node.func, ast.Attribute)
                        and node.func.attr == target_name
                    ):
                        accessed_name = node.func.attr
                        action_type = "Method Call"

                # ② 어트리뷰트 접근: obj.target
                elif (
                    isinstance(node, ast.Attribute) and node.attr == target_name
                ):
                    # Call의 func로 처리된 것은 중복 방지
                    if not (
                        isinstance(getattr(node, "parent", None), ast.Call)
                        and node.parent.func == node
                    ):
                        accessed_name = node.attr
                        action_type = "Attribute Access"

                # ③ 일반 변수/함수 이름 참조
                elif isinstance(node, ast.Name) and node.id == target_name:
                    # 정의(Store) 지점이나 Call의 func로 이미 처리된 경우 제외
                    if isinstance(
                        node.ctx, ast.Load
                    ) and not isinstance(
                        getattr(node, "parent", None), ast.Call
                    ):
                        accessed_name = node.id
                        action_type = "Variable Reference"

                # 타겟 요소가 사용된 지점을 발견한 경우
                if accessed_name:
                    caller_scope = self._get_scope_path(node)
                    try:
                        snippet = ast.unparse(node)
                    except AttributeError:
                        snippet = target_name

                    call_info = {
                        "file": str(file_path),
                        "module": mod_name,
                        "line": getattr(node, "lineno", 0),
                        "caller_scope": caller_scope,  # 호출이 일어난 내부 스코프
                        "action": action_type,
                        "code_snippet": snippet,
                    }

                    # 정의된 파일과 동일하면 로컬(3), 다르면 외부(2)
                    if file_path in defined_files:
                        result["3_local_calls"].append(call_info)
                    else:
                        result["2_external_calls"].append(call_info)

        return result

if __name__ == "__main__":
    # 1. 탐색할 폴더 경로 지정
    target_directory = r"E:\autoconstruction"

    # 2. FuncExport 객체 생성 (폴더 내 모든 .py 수집 및 AST 파싱)
    exporter = FuncExport(target_directory)

    # 3. 검토할 대상 이름 (함수/메서드/어트리뷰트/변수 이름 아무거나)
    target_element = "bulk_add_nodes"

    # 4. 분석 실행
    report = exporter.analyze_element(target_element)

    # 5. 결과 확인
    import pprint

    pprint.pprint(report)