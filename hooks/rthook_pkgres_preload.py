"""
Runtime hook: pre-load pkg_resources vendor dependencies before pyi_rth_pkgres runs.

pkg_resources/__init__.py (modern setuptools >=65) imports jaraco.*, platformdirs,
and more_itertools via its extern/vendor proxy. In a frozen app, these imports
fail with a circular-import error because pkg_resources is only partially
initialized when the proxy tries to load them.

By pre-loading the standalone packages here (before pyi_rth_pkgres runs),
sys.modules is already populated when the VendorImporter's fallback path runs,
so the fallback succeeds without re-importing.
"""

import sys

_PRELOAD = [
    'platformdirs',
    'more_itertools',
    'jaraco',
    'jaraco.text',
    'jaraco.functools',
    'jaraco.context',
    'jaraco.collections',
]

for _mod in _PRELOAD:
    if _mod not in sys.modules:
        try:
            __import__(_mod)
        except Exception:
            pass
