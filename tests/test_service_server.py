import importlib


def test_server_module_imports_without_grpc():
    # server.py must be importable with no grpc installed; grpc is lazy in serve().
    mod = importlib.import_module("labjury.service.server")
    assert hasattr(mod, "serve")
