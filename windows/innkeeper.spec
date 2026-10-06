# PyInstaller build file for the Windows app. Run from the project root:
#   pyinstaller windows/innkeeper.spec --noconfirm
import os

import django
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))


def walk_modules(package_dir, prefix, skip=()):
    """List every module in a package by walking its folder.

    collect_submodules() imports each module to find it, which fails for Django
    code before settings are loaded, so those modules would silently be left out.
    """
    found = []
    for dirpath, dirnames, filenames in os.walk(package_dir):
        rel = os.path.relpath(dirpath, package_dir)
        parts = [] if rel == "." else rel.split(os.sep)
        dotted = ".".join([prefix] + parts)
        if any(dotted == s or dotted.startswith(s + ".") for s in skip) or "__pycache__" in parts:
            dirnames[:] = []
            continue
        if "__init__.py" not in filenames:
            dirnames[:] = []
            continue
        found.append(dotted)
        for f in filenames:
            if f.endswith(".py") and f != "__init__.py":
                found.append(f"{dotted}.{f[:-3]}")
    return found


def here(*parts):
    return os.path.join(ROOT, *parts)


datas = [
    (here("templates"), "templates"),
    (here("staticfiles"), "staticfiles"),
    (here("static"), "static"),
    (here("locale"), "locale"),
    (here("windows", "innkeeper.ico"), "windows"),
]
datas += collect_data_files("django")

hiddenimports = (
    walk_modules(here("apps"), "apps", skip=("apps.accounts.tests", "apps.core.tests", "apps.frontdesk.tests",
                                            "apps.housekeeping.tests", "apps.outlets.tests", "apps.finance.tests"))
    + walk_modules(here("config"), "config")
    + walk_modules(os.path.dirname(django.__file__), "django", skip=("django.contrib.gis", "django.test", "django.db.backends.oracle", "django.db.backends.mysql", "django.db.backends.postgresql"))
    + collect_submodules("whitenoise")
    + collect_submodules("waitress")
    + ["dj_database_url", "qrcode", "qrcode.image.svg", "qrcode.image.pure", "win32print", "win32timezone"]
)

a = Analysis(
    [here("windows", "launcher.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["psycopg", "psycopg2", "gunicorn", "pytest"],
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="InnKeeper",
    icon=here("windows", "innkeeper.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="InnKeeper")
