"""
Smoke test for the scaffold: confirms that maiml_domain -- declared in
pyproject.toml as a git dependency pinned to MaiML-Domain's v0.1.0 tag -- is
actually installed and importable alongside pymaiml itself.

Run with:
    pip install -e ".[dev]"
    pytest
"""
import maiml_domain

import pymaiml


def test_maiml_domain_is_importable():
    assert hasattr(maiml_domain, "MaimlRootType")


def test_pymaiml_package_has_version():
    assert pymaiml.__version__ == "0.1.0"
