from app.main import app


def api_operations() -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for path, path_item in app.openapi()["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method in {"get", "post", "put", "patch", "delete"}:
            if method in path_item:
                operations.add((method.upper(), path))
    return operations


def test_business_api_routes_only_use_get_or_post() -> None:
    assert {method for method, _ in api_operations()} <= {"GET", "POST"}


def test_post_business_routes_do_not_use_path_parameters() -> None:
    for method, path in api_operations():
        if method == "POST":
            assert "{" not in path


def test_revised_api_paths_exist() -> None:
    expected = {
        ("GET", "/api/auth/check-login"),
        ("POST", "/api/knowledge/documents/upload"),
        ("GET", "/api/knowledge/documents/list"),
        ("GET", "/api/knowledge/documents/detail/{document_id}"),
        ("POST", "/api/knowledge/documents/delete"),
        ("POST", "/api/knowledge/documents/reprocess"),
        ("POST", "/api/knowledge/chunks/update-content-context"),
        ("POST", "/api/knowledge/chunks/enable-retrieval"),
        ("POST", "/api/system/services/test"),
    }
    assert expected <= api_operations()


def test_all_api_routes_declare_unified_response_model() -> None:
    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/"):
            fields = getattr(route.response_model, "model_fields", {})
            assert {"code", "msg", "data"} <= set(fields)
