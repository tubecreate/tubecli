import sqlite3, json

db_path = r'C:\tubecreate-vue\tubecli\data\content_studio\content_studio.db'
conn = sqlite3.connect(db_path)

# Get drama 99 chars without image
char_cols = [r[1] for r in conn.execute("PRAGMA table_info(characters)").fetchall()]
chars = conn.execute("SELECT * FROM characters WHERE drama_id=99 ORDER BY id", ()).fetchall()
char_dicts = [dict(zip(char_cols, c)) for c in chars]

print(f"Drama 99 - Total chars: {len(char_dicts)}")
for c in char_dicts:
    has_img = bool((c.get('image_url') or '').strip())
    has_app = bool((c.get('appearance') or '').strip())
    app_len = len((c.get('appearance') or '').strip())
    would_gen = has_app and not has_img
    name_bytes = repr(c.get('name', ''))
    print(f"  [{c['id']}] name={name_bytes} | image={'YES' if has_img else 'NO'} | appearance={'YES' if has_app else 'NO'}({app_len}chars) | would_gen={'YES' if would_gen else 'NO'}")
    if has_app and not has_img:
        # Show first 100 chars of appearance
        app_preview = (c.get('appearance') or '')[:100].encode('ascii', errors='replace').decode('ascii')
        print(f"    appearance preview: {app_preview}...")

conn.close()
