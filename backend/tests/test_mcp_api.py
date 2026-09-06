from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_mcp_registry_is_exposed_without_hidden_controller_tooling() -> None:
    response = client.get("/mcp/tools")
    assert response.status_code == 200
    tools = response.json()
    names = {item["name"] for item in tools}
    assert {
        "search_logs",
        "query_metrics",
        "execute_sql",
        "list_deployments",
        "inspect_deployment",
        "inspect_commit",
        "inspect_git_diff",
        "search_code",
        "search_documentation",
        "run_diagnostic",
    } == names
    assert all("fault" not in item["name"] for item in tools)


def test_unknown_tool_is_blocked() -> None:
    response = client.post("/mcp/invoke", json={"tool": "run_shell", "arguments": {}})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["error"]["code"] == "invalid_arguments"
