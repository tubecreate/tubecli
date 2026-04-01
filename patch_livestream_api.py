import os

api_path = r"c:\tubecreate-vue\tubecli\data\extensions_external\livestream\livestream_api.py"

with open(api_path, 'r', encoding='utf-8') as f:
    text = f.read()

get_man = """
def get_manager():
    import sys, os
    d = os.path.dirname(os.path.abspath(__file__))
    added = False
    if d not in sys.path:
        sys.path.insert(0, d)
        added = True
    try:
        from extension import livestream_manager
        return livestream_manager
    finally:
        if added:
            try:
                sys.path.remove(d)
            except ValueError:
                pass
"""

text = text.replace('router = APIRouter(prefix="/api/v1/livestream", tags=["livestream"])', 
                    'router = APIRouter(prefix="/api/v1/livestream", tags=["livestream"])' + get_man)

text = text.replace('    from extension import livestream_manager', '    livestream_manager = get_manager()')

with open(api_path, 'w', encoding='utf-8') as f:
    f.write(text)

print("livestream_api.py patched successfully!")
