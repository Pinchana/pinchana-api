import runpy
import sys
import types
from pathlib import Path


def test_redis_socket_timeout_exceeds_blocking_pop_timeout(monkeypatch):
    redis_calls = []

    class FakeRedisClient:
        @staticmethod
        def from_url(url, **kwargs):
            redis_calls.append((url, kwargs))
            return object()

    fake_docker = types.SimpleNamespace(
        errors=types.SimpleNamespace(
            ImageNotFound=type("ImageNotFound", (Exception,), {}),
            NotFound=type("NotFound", (Exception,), {}),
        ),
        from_env=lambda: object(),
    )
    monkeypatch.setitem(sys.modules, "docker", fake_docker)
    monkeypatch.setitem(
        sys.modules,
        "redis",
        types.SimpleNamespace(Redis=FakeRedisClient),
    )

    orchestrator_dir = Path(__file__).parents[1] / "orchestrator"
    monkeypatch.syspath_prepend(str(orchestrator_dir))
    module = runpy.run_path(
        str(orchestrator_dir / "main.py"),
        run_name="pinchana_dlp_orchestrator_test",
    )

    block_timeout = module["BLOCKING_POP_TIMEOUT_SECONDS"]
    socket_timeout = module["REDIS_SOCKET_TIMEOUT_SECONDS"]
    assert socket_timeout > block_timeout
    assert redis_calls == [
        (
            "redis://localhost:6379/0",
            {
                "decode_responses": True,
                "socket_timeout": socket_timeout,
            },
        )
    ]
