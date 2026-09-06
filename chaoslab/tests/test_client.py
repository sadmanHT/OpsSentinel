import httpx

from chaoslab.client import ChaosLabClient
from chaoslab.models import FaultType, Severity


def test_client_inject_and_status(monkeypatch) -> None:
    def fake_post(url, json, timeout):
        assert url.endswith("/faults/inject")
        assert timeout == 3
        assert json["fault"] == "n_plus_one"
        assert json["service"] == "checkout"
        return httpx.Response(
            200,
            json={
                **json,
                "active": True,
                "generation": 1,
            },
            request=httpx.Request("POST", url),
        )

    def fake_get(url, timeout):
        assert url.endswith("/faults")
        assert timeout == 3
        return httpx.Response(
            200,
            json=[
                {
                    "fault": "n_plus_one",
                    "service": "checkout",
                    "severity": "P2",
                    "seed": 42,
                    "configuration": {},
                    "active": True,
                    "generation": 1,
                }
            ],
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(httpx, "get", fake_get)

    client = ChaosLabClient("http://controller", timeout=3)
    state = client.inject(
        FaultType.N_PLUS_ONE,
        service="checkout",
        severity=Severity.P2,
    )
    assert state.generation == 1
    assert client.status() == [state]


def test_client_restore_operations(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json, timeout):
        calls.append((url, json))
        removed = 1 if url.endswith("/faults/restore") else 3
        return httpx.Response(
            200,
            json={"status": "restored", "removed": removed},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = ChaosLabClient("http://controller")

    assert client.restore("checkout", FaultType.N_PLUS_ONE) == 1
    assert client.restore_all() == 3
    assert calls[0][1] == {"service": "checkout", "fault": "n_plus_one"}
    assert calls[1][1] == {}
