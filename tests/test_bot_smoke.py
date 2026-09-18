"""bot 子包与新依赖能被 import。"""
import importlib


def test_src_bot_importable():
    mod = importlib.import_module("src.bot")
    assert mod is not None


def test_telegram_imported():
    import telegram
    from telegram.ext import Application  # noqa: F401
    assert hasattr(telegram, "__version__")


def test_apscheduler_imported():
    from apscheduler.schedulers.asyncio import AsyncIOScheduler  # noqa: F401


def test_pytest_asyncio_imported():
    import pytest_asyncio  # noqa: F401
    assert pytest_asyncio.__version__ >= "1.0"


def test_httpx_imported():
    import httpx  # noqa: F401