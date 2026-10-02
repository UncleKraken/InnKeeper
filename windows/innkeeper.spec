# PyInstaller build file for the Windows app. Run from the project root:
#   pyinstaller windows/innkeeper.spec --noconfirm
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))


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
    collect_submodules("apps")
    + collect_submodules("config")
    + collect_submodules("django")
    + collect_submodules("whitenoise")
    + ["waitress", "dj_database_url", "qrcode", "qrcode.image.svg"]
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
