# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['appOMEGAS.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('../translations', 'translations'),
        ('../assets', 'assets'),
        ('../IMAGENES', 'IMAGENES'),
        ('../Pantallas', 'Pantallas'),
        ('../stock_sap_omegas.json', '.'),
    ],
    hiddenimports=['pyodbc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='omegasexten_v.2_petr',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)