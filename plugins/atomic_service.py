import ast
from pathlib import Path

from PyQt5.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from api.utils import select_function
from funcElementAnatomy import ModuleCodeAnalyzer
from funcExports import FuncExport
from funcInfluence import FuncInfluenceAnalyzer
from funcOrigin import FuncOrigin
from funcdocs_plugins.api import FuncDocsPlugin, FunctionContext


def _annotation(node):
    if node is None:
        return "미지정"
    return ast.unparse(node)


def _source(node, source):
    value = ast.get_source_segment(source, node)
    return " ".join(value.split()) if value else type(node).__name__


def _get_parameters(function_node):
    args = function_node.args
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults))
    defaults.extend(args.defaults)
    parameters = [
        (
            argument.arg,
            _annotation(argument.annotation),
            ast.unparse(default) if default is not None else "",
        )
        for argument, default in zip(positional, defaults)
    ]
    parameters.extend(
        (argument.arg, _annotation(argument.annotation), "")
        for argument in args.kwonlyargs
    )
    if args.vararg:
        parameters.append(
            ("*" + args.vararg.arg, _annotation(args.vararg.annotation), "")
        )
    if args.kwarg:
        parameters.append(
            ("**" + args.kwarg.arg, _annotation(args.kwarg.annotation), "")
        )
    return parameters


def _function_body_nodes(function_node):
    pending = list(reversed(function_node.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(
            node,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
                ast.ClassDef,
                ast.Lambda,
            ),
        ):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _definition_names(tree, class_name):
    module_functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    class_methods = set()
    if class_name:
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                class_methods.update(
                    child.name
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
                break
    return module_functions, class_methods


def analyze_atomic_service(source, function_name, class_name=None):
    tree = ast.parse(source)
    selection = select_function(tree, function_name, class_name)
    function_node = selection["node"]
    module_functions, class_methods = _definition_names(tree, class_name)

    branches = []
    calls = []
    internal_calls = []
    returns = []
    raises = []
    handled_exceptions = []
    mutations = []
    assignments = []
    parameter_names = {
        name for name, _annotation_name, _default in _get_parameters(function_node)
    }
    parameter_uses = {name: set() for name in parameter_names}

    for node in _function_body_nodes(function_node):
        if isinstance(node, (ast.If, ast.While)):
            branches.append(
                (node.lineno, _source(node.test, source), type(node).__name__)
            )
        elif isinstance(node, ast.IfExp):
            branches.append(
                (node.lineno, _source(node.test, source), "조건식")
            )
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            branches.append((node.lineno, _source(node.iter, source), "반복"))
        elif isinstance(node, ast.Try):
            for handler in node.handlers:
                exception_name = _annotation(handler.type)
                handled_exceptions.append((handler.lineno, exception_name))
        elif isinstance(node, ast.Match):
            branches.append((node.lineno, _source(node.subject, source), "패턴 분기"))
        elif isinstance(node, ast.Call):
            call_name = _source(node.func, source)
            calls.append((node.lineno, call_name))
            root = node.func
            while isinstance(root, ast.Attribute):
                root = root.value
            is_local_call = (
                isinstance(node.func, ast.Name)
                and node.func.id in module_functions
            ) or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in class_methods
                and isinstance(root, ast.Name)
                and root.id in {"self", "cls"}
            )
            if is_local_call:
                recursive = call_name in {
                    function_name,
                    f"self.{function_name}",
                    f"cls.{function_name}",
                }
                if not recursive:
                    internal_calls.append((node.lineno, call_name))
        elif isinstance(node, ast.Return):
            value = _source(node.value, source) if node.value else "None"
            returns.append((node.lineno, value))
        elif isinstance(node, ast.Raise):
            exception = (
                _source(node.exc, source)
                if node.exc
                else "현재 예외 재발생"
            )
            raises.append((node.lineno, exception))
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Delete)):
            targets = (
                node.targets
                if isinstance(node, (ast.Assign, ast.Delete))
                else [getattr(node, "target", None)]
            )
            for target in targets:
                if isinstance(target, (ast.Attribute, ast.Subscript)):
                    mutations.append((node.lineno, _source(target, source)))
                elif isinstance(target, ast.Name) and not isinstance(node, ast.Delete):
                    value = getattr(node, "value", None)
                    if value is not None:
                        assignments.append(
                            (node.lineno, target.id, _source(value, source))
                        )

        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if node.id in parameter_uses:
                parameter_uses[node.id].add(node.lineno)

    return {
        "function_node": function_node,
        "selection": selection,
        "parameters": _get_parameters(function_node),
        "parameter_uses": parameter_uses,
        "assignments": assignments,
        "return_annotation": _annotation(function_node.returns),
        "branches": branches,
        "calls": calls,
        "internal_calls": internal_calls,
        "returns": returns,
        "raises": raises,
        "handled_exceptions": handled_exceptions,
        "mutations": mutations,
    }


def assess_function_unit(result, influence):
    calls = result["calls"]
    read_verbs = ("get", "find", "load", "read", "fetch", "query", "select", "list")
    write_verbs = (
        "save", "update", "delete", "insert", "create", "write", "commit",
        "flush", "remove", "add", "persist",
    )
    read_calls = [
        name for _, name in calls
        if name.rsplit(".", 1)[-1].lower().startswith(read_verbs)
    ]
    write_calls = [
        name for _, name in calls
        if name.rsplit(".", 1)[-1].lower().startswith(write_verbs)
    ]
    changed_state = bool(result["mutations"]) or any(
        influence.get(key)
        for key in (
            "actual_param_mutations",
            "actual_global_mutations",
            "global_obj_mutations",
        )
    )
    external_io = bool(influence.get("io_side_effects"))
    has_read = bool(read_calls)
    has_write = bool(write_calls) or changed_state

    if has_read and has_write:
        role = "read_modify_command"
        role_evidence = read_calls + write_calls
    elif has_write:
        role = "state_change"
        role_evidence = write_calls or [
            f"상태 변경 {len(result['mutations'])}건"
        ]
    elif has_read:
        role = "query"
        role_evidence = read_calls
    elif external_io:
        role = "integration"
        role_evidence = [
            item.get("func", "I/O")
            for item in influence.get("io_side_effects", [])
        ]
    elif result["branches"] and result["raises"]:
        role = "validation"
        role_evidence = [
            f"분기 {len(result['branches'])}건",
            f"예외 발생 {len(result['raises'])}건",
        ]
    elif result["branches"]:
        role = "decision"
        role_evidence = [f"분기 {len(result['branches'])}건"]
    elif result["assignments"] or result["returns"]:
        role = "transform"
        role_evidence = [
            f"값 할당 {len(result['assignments'])}건",
            f"반환 {len(result['returns'])}건",
        ]
    else:
        role = "helper_unknown"
        role_evidence = []

    role_basis = []
    if read_calls or write_calls:
        role_basis.append(
            "조회/변경 호출은 메서드 이름 접두어로 추정했습니다."
        )
    if changed_state:
        role_basis.append(
            "상태 변경은 대입 AST와 부작용 분석 결과에서 확인했습니다."
        )
    if external_io:
        role_basis.append(
            "외부 I/O는 부작용 분석기가 감지한 항목입니다."
        )
    if not role_basis:
        role_basis.append(
            "분기, 예외, 할당, 반환 같은 AST 구조를 근거로 했습니다."
        )

    internal_targets = sorted({
        name for _, name in result["internal_calls"]
    })
    internal_call_count = len(result["internal_calls"])
    if internal_call_count > 1:
        boundary = "assembly_candidate"
        rationale = (
            f"내부 위임 호출이 {internal_call_count}회 관찰됩니다. "
            "이 함수가 흐름을 조정하는 상위 단위인지 검토하세요."
        )
    elif internal_targets:
        boundary = "delegation_candidate"
        rationale = (
            "내부 함수 하나로 위임합니다. 단순 전달 래퍼인지, "
            "독립된 업무 단위인지는 호출자와 계약을 함께 확인해야 합니다."
        )
    elif external_io and has_write:
        boundary = "review_boundary"
        rationale = (
            "상태 변경과 외부 I/O가 함께 나타납니다. 한 업무 단위의 "
            "필수 효과인지, 분리할 책임인지 확인하세요."
        )
    elif role != "helper_unknown":
        boundary = "atomic_candidate"
        rationale = (
            "독립적인 내부 위임 없이 하나의 주된 작업 역할이 관찰됩니다. "
            "정적 분석만으로 업무 응집성을 확정할 수는 없습니다."
        )
    else:
        boundary = "review_boundary"
        rationale = (
            "작업 역할을 뒷받침할 충분한 신호가 없습니다. "
            "호출자와 요구사항을 확인하세요."
        )

    return {
        "role": role,
        "role_evidence": role_evidence,
        "role_basis": role_basis,
        "boundary": boundary,
        "rationale": rationale,
        "internal_targets": internal_targets,
        "internal_call_count": internal_call_count,
        "read_calls": read_calls,
        "write_calls": write_calls,
        "external_io": external_io,
        "changed_state": changed_state,
    }


class AtomicServicePlugin(FuncDocsPlugin):
    plugin_id = "atomic_service"
    name = "서비스 기능 단위 분석"
    description = (
        "선택한 함수의 주된 작업 역할과 내부 위임, 상태 변경, 외부 효과를 "
        "근거와 함께 분석해 엔진 기능 단위 후보를 표시합니다."
    )
    default_enabled = True
    order = 30
    ROLE_LABELS = {
        "read_modify_command": "업무 처리 (조회 + 변경)",
        "state_change": "상태 변경",
        "query": "조회",
        "integration": "외부 연동",
        "validation": "검증 / 판단",
        "decision": "판단 / 분기",
        "transform": "값 계산 / 변환",
        "helper_unknown": "보조 로직 / 역할 미확인",
    }
    BOUNDARY_LABELS = {
        "atomic_candidate": "원자 작업 후보",
        "delegation_candidate": "위임 함수 후보",
        "assembly_candidate": "조립 함수 후보",
        "review_boundary": "경계 검토",
    }

    def __init__(self):
        self.widget = None
        self.summary = None
        self.tree = None
        self._exporters = {}

    def create_widget(self, parent):
        self.widget = QWidget(parent)
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(8, 8, 8, 8)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setObjectName("pluginSummary")
        layout.addWidget(self.summary)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["영역", "항목", "근거"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 100)
        self.tree.setColumnWidth(1, 200)
        layout.addWidget(self.tree, stretch=1)
        self.clear()
        return self.widget

    def on_function_selected(self, context: FunctionContext):
        source = "\n".join(context.source_lines)
        result = analyze_atomic_service(
            source, context.function_name, context.class_name
        )
        function_node = result["function_node"]
        anatomy = ModuleCodeAnalyzer(context.file_path)
        if anatomy.tree is None:
            raise ValueError(
                f"선택한 파일을 다시 분석할 수 없습니다: {context.file_path}"
            )
        origin = FuncOrigin(
            anatomy, context.function_name, context.class_name
        )
        influence_analyzer = FuncInfluenceAnalyzer(
            anatomy.tree, context.function_name, context.class_name
        )
        influence = influence_analyzer.analyze().get(context.function_name, {})
        unit = assess_function_unit(result, influence)
        exporter = self._get_exporter(context.file_path)
        export_report = exporter.analyze_element(
            f"{Path(context.file_path).resolve()}:{function_node.lineno}"
        )
        qualified_name = (
            f"{context.class_name}.{context.function_name}"
            if context.class_name
            else context.function_name
        )
        role_label = self.ROLE_LABELS[unit["role"]]
        boundary_label = self.BOUNDARY_LABELS[unit["boundary"]]
        self.summary.setText(
            f"{boundary_label} · {role_label} · {qualified_name} · "
            f"{Path(context.file_path).name}:{function_node.lineno}\n"
            f"{unit['rationale']}"
        )
        self.tree.clear()

        self._add_group("입력", [
            (
                name,
                f"타입: {annotation}"
                + (f", 기본값: {default}" if default else "")
                + (
                    ", 사용 위치: "
                    + ", ".join(map(str, sorted(result["parameter_uses"][name])))
                    if result["parameter_uses"][name]
                    else ", 함수 본문에서 사용되지 않음"
                ),
            )
            for name, annotation, default in result["parameters"]
        ])
        self._add_group("출력", [
            ("반환 타입", result["return_annotation"]),
            *[
                (f"return · {line}", value)
                for line, value in result["returns"]
            ],
        ])
        self._add_group("조건/분기", [
            (f"{kind} · {line}", expression)
            for line, expression, kind in result["branches"]
        ])
        self._add_group("내부 위임", [
            (f"호출 · {line}", name)
            for line, name in result["internal_calls"]
        ])
        self._add_group(
            "작업 단위 근거",
            [
                ("주된 역할", role_label),
                *[
                    ("관찰 근거", evidence)
                    for evidence in unit["role_evidence"]
                ],
                *[
                    ("추정 방식", basis)
                    for basis in unit["role_basis"]
                ],
                (
                    "판정 범위",
                    "정적 구조 기반 후보이며 업무상 응집성은 검토가 필요합니다.",
                ),
            ],
        )
        self._add_group("값의 흐름", [
            (f"{name} · {line}", f"← {value}")
            for line, name, value in result["assignments"]
        ])
        self._add_group("함수 호출", [
            (f"호출 · {line}", name)
            for line, name in result["calls"]
        ])

        read_set, write_set = context.refactor_set
        self._add_group(
            "읽기",
            [
                (f"{category} · {type_info}", expression)
                for category, values in read_set.items()
                for type_info, expression in values
            ],
        )
        self._add_group(
            "쓰기",
            [
                (f"{category} · {type_info}", expression)
                for category, values in write_set.items()
                for type_info, expression in values
            ],
        )
        self._add_group("상태 변경", [
            (f"대상 · {line}", target)
            for line, target in result["mutations"]
        ])
        self._add_group("실패 경로", [
            *[
                (f"raise · {line}", exception)
                for line, exception in result["raises"]
            ],
            *[
                (f"처리 · {line}", exception)
                for line, exception in result["handled_exceptions"]
            ],
        ])
        self._add_group(
            "요소 구조",
            [
                (item, ", ".join(map(str, lines)))
                for item, lines in anatomy.get_function_summary(
                    context.function_name, context.class_name
                ).items()
            ],
        )
        self._add_group(
            "요소 출처",
            [
                (f"{category} · {name}", description)
                for category, elements in origin.categorized_origins.items()
                for name, description in elements.items()
            ],
        )
        self._add_influence(influence)
        self._add_export_report(export_report)

    def _get_exporter(self, file_path):
        target_directory = Path(file_path).resolve().parent
        cache_key = str(target_directory)
        python_files = sorted(target_directory.rglob("*.py"))
        fingerprint = tuple(
            (str(path), path.stat().st_mtime_ns, path.stat().st_size)
            for path in python_files
        )
        cached = self._exporters.get(cache_key)
        if cached is None or cached[0] != fingerprint:
            exporter = FuncExport(target_directory)
            self._exporters[cache_key] = (fingerprint, exporter)
            return exporter
        return cached[1]

    def _add_influence(self, influence):
        entries = []
        for key in (
            "actual_param_mutations",
            "param_rebindings",
            "actual_global_mutations",
            "global_obj_mutations",
            "io_side_effects",
            "mutable_default_args",
            "escaped_params_to_calls",
            "escaped_params_to_globals",
            "returned_param_aliases",
            "shallow_copy_risks",
        ):
            for item in influence.get(key, []):
                line = item.get("line", "?")
                description = item.get(
                    "desc",
                    item.get("expr")
                    or item.get("called_func")
                    or item.get("func")
                    or item.get("var")
                    or str(item),
                )
                entries.append((f"{key} · {line}", description))

        for parameter, state in influence.get("params_summary", {}).items():
            status = []
            if state.get("mutated"):
                status.append("변경됨")
            if state.get("rebound"):
                status.append("재할당됨")
            entries.append((
                f"파라미터 · {parameter}",
                ", ".join(status) if status else "변경 없음",
            ))
        self._add_group("영향/부작용", entries)

    def _add_export_report(self, report):
        entries = []
        for key, label in (
            ("1_defined_locations", "정의"),
            ("2_external_calls", "외부 참조"),
            ("3_local_calls", "내부 참조"),
        ):
            locations = report.get(key, [])
            entries.append((f"{label} 수", str(len(locations))))
            for location in locations:
                scope = location.get("scope", "")
                line = location.get("line", "?")
                file_path = location.get("file", "")
                action = location.get("action", location.get("type", ""))
                snippet = location.get(
                    "code_snippet", location.get("element_name", "")
                )
                entries.append((
                    f"{label} · {Path(file_path).name}:{line}",
                    f"{action} {scope} — {snippet}".strip(),
                ))
        self._add_group("모듈 사용 관계", entries)

    def _add_group(self, category, entries):
        if entries:
            for label, evidence in entries:
                QTreeWidgetItem(self.tree, [category, label, evidence])
        else:
            QTreeWidgetItem(self.tree, [category, "감지된 항목 없음", ""])

    def clear(self):
        if self.summary is not None:
            self.summary.setText("함수를 선택하면 서비스 원자성 분석 결과가 표시됩니다.")
        if self.tree is not None:
            self.tree.clear()


def create_plugin():
    return AtomicServicePlugin()
