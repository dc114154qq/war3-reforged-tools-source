from __future__ import annotations

import ctypes
from pathlib import Path

import pytest

from war3_selection_limit_tool import (
    COMMAND_STRUCT,
    PATCH_COUNT,
    run_self_test,
)


ROOT = Path(__file__).resolve().parent
HELPER = (
    ROOT /
    "tools" /
    "war3_selection_limit_helper_v27_transaction_observer.dll"
)


def test_command_protocol_size_is_stable() -> None:
    assert PATCH_COUNT == 14
    assert COMMAND_STRUCT.size == 424


@pytest.mark.skipif(not HELPER.exists(), reason="selection limit helper has not been built")
def test_helper_runtime_self_tests() -> None:
    run_self_test(HELPER)


@pytest.mark.skipif(not HELPER.exists(), reason="selection limit helper has not been built")
def test_helper_exports_hook() -> None:
    helper = ctypes.WinDLL(str(HELPER))
    assert helper.War3SelectionLimitHookProc
    assert helper.War3SelectionLimitConfigureAuxiliaryBreakpoints
