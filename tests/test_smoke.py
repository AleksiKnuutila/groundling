"""Smoke test: package imports."""
import groundling


def test_package_importable():
    assert groundling.__name__ == "groundling"
