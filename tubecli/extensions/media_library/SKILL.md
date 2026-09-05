# Media Library

A shared bag of raw material — images, GIFs and videos — that every extension
can draw from. The user gathers material once; extensions point at a collection
by id and the machine picks a file.

## Why it exists

Each extension used to grow its own private store, so the same picture had to be
uploaded several times and fixing it in one place left the other copies stale.
One library, many consumers.

## Concepts

- **Collection**: a named bag. It has an `id` (ASCII, immutable, used as the
  folder name) and a display `name` that can be renamed freely — renaming never
  touches the folder.
- **File**: an image, GIF or video inside a collection. Order is stable.
- **Picking**: `random` (any file), `cycle` (walks the whole collection before
  repeating, so two consecutive uses do not collide), `ai` (the caller supplies
  the filename a model chose).

## Endpoints

Prefix `/api/v1/media`. Page at `/media-library`.

| Route | What it does |
|---|---|
| `GET/POST /collections` | list, create |
| `GET/PUT/DELETE /collections/{cid}` | open, rename, remove |
| `POST /collections/{cid}/files` | upload one file (multipart `file`) |
| `POST /collections/{cid}/import` | copy a file already on disk, `{path}` |
| `GET/DELETE /collections/{cid}/files/{name}` | serve, remove |
| `POST /collections/{cid}/pick` | `{mode, commit, file, kind}` → one file |
| `GET /health` | how many collections and files, and where they live |

## Using it from another extension

```python
from tubecli.extensions import media_library

for c in media_library.collections():
    print(c["id"], c["name"], c["count"])

path, why = media_library.pick_media("kho_avatar", mode="cycle", kind="image")
if path:
    ...        # dùng file
else:
    log.warning("kho rỗng: %s", why)
```

Import it lazily and tolerate its absence: an older TubeCLI may not have it, and
a missing library should degrade one layer, not break the whole job.

## When an agent uses this

Ask for a collection by name, then pick. Pictures come from the bag; **text does
not** — write the words from the actual content, and let the machine draw them
with real fonts. That split is the whole point: material is reused, wording is
written fresh for each video.

Thumbnail Studio consumes this directly: a `store` layer declaring
`"store": "lib:<collection_id>"` draws from here instead of its own folder.
