import sys, os, shutil
from tubecli.config import EXTENSIONS_EXTERNAL_DIR
from tubecli.core.extension_manager import extension_manager

p = os.path.join(EXTENSIONS_EXTERNAL_DIR, 'browser-control')
if os.path.exists(p):
    print(f"Removing existing extension at {p}")
    shutil.rmtree(p, ignore_errors=True)

print("Starting ensure_essential_extensions...")
extension_manager.ensure_essential_extensions()
print("Done.")
