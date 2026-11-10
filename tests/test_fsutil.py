from __future__ import annotations

import os

import pytest

from hydroseason._fsutil import _long_path


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path prefixes")
def test_long_path_prefixes_local_and_network_paths():
    assert _long_path(r"C:\cache") == r"\\?\C:\cache"
    assert _long_path(r"\\server\share\cache") == r"\\?\UNC\server\share\cache"
    assert _long_path(r"\\?\C:\cache") == r"\\?\C:\cache"
