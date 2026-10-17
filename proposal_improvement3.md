# Further improvements aiset needs, from the aidir host

file version 1.0.0

Written by the aidir side **after** `proposal_improvement2.md` was implemented.
aiset is a separate project: nothing here has been applied to `aiset/`, and
nothing here blocks aidir.

`proposal_improvement2.md` is closed and is not reopened by this document. Its
items 1 to 4 are done in `aiset/`, and the two notes that would have been added
to its items 1 and 2 are not needed: both items already carry an "As
implemented" status, so there is nothing left for those notes to propose. The
host-side reference implementations they pointed at still exist and are listed
under "Reference material" below, for whoever works on the item-5 leftovers.

The one genuinely new item was found on 2026-10-17 while fixing a real
front-end bug, and is the reason this document exists.

**Status: nothing here blocks the migration.** aidir already pins the current
behaviour with a test, so the item is tracked, not blocking.

**As implemented (2026-10-17).** Item 1 is done: `GET /documents` requires
`settings_read_source` and returns `403` otherwise; `/health` stays public; a
host can opt into a public list with `public_documents=True`. aidir's pinning
test now fails as intended.

Reproduce with `cd aiset && ./test.sh`.

---

## 1 — `GET /api/settings/documents` answers an unauthenticated caller
> **As implemented.** The `/documents` branch calls `Service.list_documents`,
> which requires `settings_read_source`; `/health` is documented as the only
> public route; `create_app` / `create_asgi_app` take `public_documents=True`
> for hosts that want a public list. Covered in `tests/test_http.py` and
> `tests/test_asgi.py`.

**Impact: low. No value is disclosed, but the route set is inconsistent.**

### What happens

Every settings route except one resolves the principal and passes it into the
service, which then checks a permission:

| Route | Permission enforced |
|---|---|
| `GET /tree`, `GET /value` (`view=source`) | `settings_read_source` |
| `GET /value` (`view=effective`) | `settings_read_effective` |
| `POST /value`, `POST /load` | `settings_write` |
| `POST /validate`, `POST /document/validate` | `settings_validate` |
| `POST /env`, `POST /merge` | write-side checks |
| **`GET /documents`** | **none** |

In `src/aiset/httpd.py` the dispatcher takes `principal` as an argument and
forwards it everywhere except this one branch:

```python
if method == "GET" and route == "/documents":
    return _json(start_response, 200, {"ok": True, "documents": sorted(service.documents)})
```

So a caller with no session, no API key and no host principal receives the
complete list of configuration document ids. In aidir that is
`main` plus the five worker documents, which discloses the worker's tool and
model inventory.

This is not a mount-level mistake and not a resolver problem: both transports
resolve the principal before the dispatcher runs (the ASGI adapter resolves an
async principal and the WSGI one calls `principal_resolver`), so the value is
already in hand and simply not used. `GET /health` is genuinely public and is
handled earlier, before any principal exists; that one is correct.

### What would fix it

Require the same read permission the rest of the surface requires, so the
route set stops being the exception:

- check `settings_read_source` in the `/documents` branch and return `403` when
  the principal lacks it, exactly as `service.tree` already does;
- keep `/health` public and say so in the table above, so the next reader does
  not re-open it;
- if a host really wants an unauthenticated document list - a liveness probe
  that wants to report the count, for instance - that should be a named
  argument rather than the accidental default, the same choice already made for
  `static_base` in `proposal_improvement2.md` item 1.

**Acceptance:** an unauthenticated `GET /documents` returns `403`; a principal
with `settings_read_source` receives the list; `tests/test_http.py` and
`tests/test_asgi.py` cover both transports.

### How aidir pins it in the meantime

`test_settings_backend.py`, `test_the_document_list_route_is_public_in_the_library`,
asserts the current `200`. It is written to fail as soon as the route is fixed
here, so the change cannot land unnoticed on the host side.

---

## Reference material for already-implemented items

Not a task, and not a change to anything in `proposal_improvement2.md`. Recorded
so the evidence is not lost when it is needed for the item-5 leftovers (the
revision diff, and anything that grows out of them).

- **Host-side shape of the double mount** (`proposal_improvement2.md` item 1):
  aidir's `webui/backend/app.py`, function `mount_settings_api`, mounts the same
  library application a second time under the asset prefix and documents why.
  `test_settings_backend.py`, class `WebUIMountTests`, proves it through the real
  FastAPI app: the mount order, every asset the page names, and the script-tag
  dependency order in `index.html`.

- **Host-side shape of document validation** (`proposal_improvement2.md` item 2):
  aidir's `test_config_descriptor.py` loads every shipped configuration document
  against its descriptor through `Service.load` with a fixture `.env`, and fails
  on any error-severity issue. Roughly sixty lines; it is what a `--config`
  command has to do and print.