"""Portable GUI entry point and hidden service roles."""
import sys

if '--serve' in sys.argv:
    sys.argv.remove('--serve')
    from server import main
    main()
elif '--listener' in sys.argv:
    from native_listener import cli
    sys.argv = [sys.argv[0], '--root', sys.argv[2]]
    cli()
elif '--watchdog' in sys.argv:
    from native_watchdog import main
    main(sys.argv[2])
elif '--self-check' in sys.argv:
    import hashlib
    import json
    from pathlib import Path
    from desktop_app import WX_HASH, Platform
    import tkinter
    import native_listener
    import native_watchdog
    p = Platform()
    assert hashlib.sha256(p.wx.read_bytes()).hexdigest() == WX_HASH
    Path(sys.argv[2]).write_text(json.dumps({'ok': True, 'frozen': bool(getattr(sys,'frozen',False)), 'nativeComponentVerified': True}), encoding='utf-8')
else:
    from desktop_app import main
    main()
