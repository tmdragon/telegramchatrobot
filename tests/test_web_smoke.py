"""src.web 包可以被 import。"""
import importlib


def test_src_web_importable():
    mod = importlib.import_module("src.web")
    assert mod is not None


def test_fastapi_installed():
    import fastapi  # noqa: F401
    assert fastapi.__version__ >= "0.115"


def test_jinja2_installed():
    import jinja2  # noqa: F401
    assert jinja2.__version__ >= "3.1"


def test_uvicorn_installed():
    import uvicorn  # noqa: F401
    assert uvicorn.__version__ >= "0.30"