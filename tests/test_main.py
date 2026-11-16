import ast
from pathlib import Path

from fastapi.routing import APIRoute

from main import app

MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"
MAX_HANDLER_LINES = 15


def test_app_imports_and_routes_are_unique():
    seen = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            pair = (method, route.path)
            assert pair not in seen, f"duplicate route: {pair}"
            seen.add(pair)

    assert seen  # at least one route was found


def _is_route_decorator(decorator: ast.expr) -> bool:
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id == "app"
        and func.attr in {"get", "post", "put", "patch", "delete"}
    )


def test_no_handler_in_main_exceeds_fifteen_lines():
    tree = ast.parse(MAIN_PY.read_text())
    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(_is_route_decorator(d) for d in node.decorator_list)
    ]

    assert handlers  # the test itself must exercise at least one handler

    for node in handlers:
        length = node.end_lineno - node.lineno + 1
        assert length <= MAX_HANDLER_LINES, f"{node.name} is {length} lines; move logic to app/services/"
