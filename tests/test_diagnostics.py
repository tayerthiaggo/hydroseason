import sys

import pytest

from hydroseason._diagnostics import (
    SUPPORTED_PYTHON,
    EnvironmentCheck,
    check_environment,
    missing_rainfall_dependencies,
)


def test_supported_python_window_matches_the_packaging_metadata():
    assert SUPPORTED_PYTHON == ((3, 10), (3, 14))


def test_core_group_reports_python_pandas_and_numpy():
    checks = {c.name: c for c in check_environment(groups=("core",))}

    assert set(checks) >= {"python", "pandas", "numpy"}
    assert all(isinstance(c, EnvironmentCheck) for c in checks.values())
    assert checks["pandas"].status == "ok"
    assert checks["numpy"].status == "ok"


def test_running_python_is_reported_ok_inside_the_supported_window():
    checks = {c.name: c for c in check_environment(groups=("core",))}
    inside = SUPPORTED_PYTHON[0] <= sys.version_info[:2] < SUPPORTED_PYTHON[1]

    assert (checks["python"].status == "ok") is inside


def test_missing_optional_dependency_is_an_error_naming_the_extra(monkeypatch):
    """A missing raster/stac dependency is not a warning: the feature that
    needs it cannot run at all. The message must name the extra that
    installs it."""
    import hydroseason._diagnostics as mod

    real_import = mod.importlib.import_module

    def blocked(name):
        if name == "s3fs":
            raise ImportError("No module named 's3fs'")
        return real_import(name)

    monkeypatch.setattr(mod.importlib, "import_module", blocked)
    checks = {c.name: c for c in check_environment(groups=("raster",))}

    assert checks["s3fs"].status == "error"
    assert "raster" in checks["s3fs"].detail


def test_missing_rainfall_dependencies_lists_the_silo_imports(monkeypatch):
    import hydroseason._diagnostics as mod

    def blocked(name):
        if name in {"s3fs", "h5netcdf"}:
            raise ImportError(f"No module named {name!r}")
        return object()

    monkeypatch.setattr(mod.importlib, "import_module", blocked)

    assert mod.missing_rainfall_dependencies() == ("h5netcdf", "s3fs")


def test_no_missing_rainfall_dependencies_when_everything_imports():
    pytest.importorskip("s3fs")
    pytest.importorskip("h5netcdf")
    pytest.importorskip("h5py")

    assert missing_rainfall_dependencies() == ()


def test_netcdf4_abi_mismatch_is_reported_as_an_error(monkeypatch):
    """Probe in a child process: a broken native extension must never be
    imported into the long-lived doctor process itself."""
    import hydroseason._diagnostics as mod

    completed = mod.subprocess.CompletedProcess(
        args=[sys.executable],
        returncode=3,
        stdout="",
        stderr=(
            "numpy.ndarray size changed, may indicate binary "
            "incompatibility. Expected 16 from C header, got 96 from PyObject"
        ),
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: completed)
    checks = {c.name: c for c in mod.check_environment(groups=("raster",))}

    assert checks["netCDF4 ABI"].status == "error"
    assert "binary incompatibility" in checks["netCDF4 ABI"].detail


def test_netcdf4_not_installed_is_ok(monkeypatch):
    import hydroseason._diagnostics as mod

    completed = mod.subprocess.CompletedProcess(
        args=[sys.executable], returncode=0, stdout="not-installed\n", stderr=""
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: completed)
    checks = {c.name: c for c in mod.check_environment(groups=("raster",))}

    assert checks["netCDF4 ABI"].status == "ok"
    assert "not installed" in checks["netCDF4 ABI"].detail


def test_netcdf4_probe_crash_is_reported_as_an_error(monkeypatch):
    import hydroseason._diagnostics as mod

    completed = mod.subprocess.CompletedProcess(
        args=[sys.executable], returncode=-1073741819, stdout="", stderr=""
    )
    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: completed)
    checks = {c.name: c for c in mod.check_environment(groups=("raster",))}

    assert checks["netCDF4 ABI"].status == "error"
    assert "exited" in checks["netCDF4 ABI"].detail
