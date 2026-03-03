# Manual Test Checklist — FastAPI Multi-Tenant Boilerplate

Stack: Python 3.12+, FastAPI, HTMX + Jinja2, SQLite database-per-tenant.
App: `http://localhost:8000`
All requests require the `X-Tenant-Slug` header.

---

## 1. Setup

```bash
make install
make migrate-registry
make create-tenant slug=acme email=owner@acme.com
make dev
```

The app is now running at `http://localhost:8000`.

Every request must include the `X-Tenant-Slug` header.

- Browser: install the **ModHeader** extension and add a persistent header `X-Tenant-Slug: acme`.
- curl: pass `-H "X-Tenant-Slug: acme"` on every command.

Default owner password created by `make create-tenant` is `changeme123`.
Change it immediately in any environment beyond local development.

---

## 2. Checklist — Authentication

### 2.1 Landing page (no auth required)

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ \
  -H "X-Tenant-Slug: acme"
# Expected: 200
```

Open `http://localhost:8000/` in a browser with `X-Tenant-Slug: acme` set in ModHeader.
The landing page must render without a login prompt.

### 2.2 Login with wrong password

```bash
curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{"email":"owner@acme.com","password":"wrong"}' | python3 -m json.tool
```

Expected response (HTTP 401):

```json
{
    "detail": "Invalid credentials"
}
```

### 2.3 Login with correct credentials and capture token

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{"email":"owner@acme.com","password":"changeme123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "TOKEN: $TOKEN"
```

Expected: the `TOKEN` variable is populated with a JWT string (three dot-separated base64url segments).

The full response body (HTTP 200) looks like:

```json
{
    "access_token": "<jwt>",
    "token_type": "bearer",
    "user_id": "<uuid>",
    "email": "owner@acme.com",
    "role": "OWNER"
}
```

### 2.4 GET /users without Authorization header

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/users \
  -H "X-Tenant-Slug: acme"
# Expected: 401
```

### 2.5 GET /users with valid token

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $TOKEN"
# Expected: 200
```

The response body is an HTML page containing the user table.
Verify `Content-Type: text/html` in the headers:

```bash
curl -sI http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $TOKEN" | grep -i content-type
# Expected: content-type: text/html; charset=utf-8
```

---

## 3. Checklist — RBAC

### 3.1 Create test users as OWNER

Run these commands while `$TOKEN` holds the OWNER JWT from section 2.3.

```bash
# Create ADMIN user
curl -s -X POST http://localhost:8000/users \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $TOKEN" \
  -d "email=admin@acme.com&password=admin123&role=ADMIN"

# Create MEMBER user
curl -s -X POST http://localhost:8000/users \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $TOKEN" \
  -d "email=member@acme.com&password=member123&role=MEMBER"

# Create VIEWER user
curl -s -X POST http://localhost:8000/users \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $TOKEN" \
  -d "email=viewer@acme.com&password=viewer123&role=VIEWER"
```

Each command returns HTTP 201 with an HTML table-row partial on success.

### 3.2 Helper: acquire tokens for each role

```bash
ADMIN_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{"email":"admin@acme.com","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

MEMBER_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{"email":"member@acme.com","password":"member123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

VIEWER_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{"email":"viewer@acme.com","password":"viewer123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### 3.3 VIEWER — GET /users: table visible, no "Add User" form

```bash
curl -s http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $VIEWER_TOKEN" | grep -i "add user"
# Expected: no match (empty output — form not rendered for VIEWER)

curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $VIEWER_TOKEN"
# Expected: 200
```

Browser check: login as `viewer@acme.com`, navigate to `/users`. The user table is visible. No "Add User" button or form is present.

### 3.4 MEMBER — POST /users: 403 Forbidden

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -X POST http://localhost:8000/users \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $MEMBER_TOKEN" \
  -d "email=new@acme.com&password=pass123&role=VIEWER"
# Expected: 403
```

### 3.5 ADMIN — GET /users: "Add User" form visible

```bash
curl -s http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | grep -i "add user"
# Expected: at least one match — the form heading or button is present
```

Browser check: login as `admin@acme.com`, navigate to `/users`. The "Add User" form is rendered above or below the user table.

### 3.6 ADMIN — POST /users via HTMX: new row appears without page reload

In the browser (logged in as `admin@acme.com`):

1. Open Chrome DevTools > Network tab, filter by `Fetch/XHR`.
2. Fill in the "Add User" form with a new email and role, then submit.
3. Verify the network request is a `POST /users` (not a full navigation).
4. Verify the new user row appears in the table without a full page reload (no spinner in browser tab).
5. The response in DevTools shows `Content-Type: text/html` and `Status: 201`.

### 3.7 ADMIN — Delete user: row removed without page reload

In the browser (logged in as `admin@acme.com`):

1. Click the Delete button next to any user row.
2. Verify a `DELETE /users/<uuid>` request appears in DevTools Network (not a navigation).
3. The row disappears from the table without a full page reload.
4. The response in DevTools shows `Status: 200` with an empty body.

### 3.8 OWNER — all operations succeed

Repeat sections 3.5, 3.6, and 3.7 using `$TOKEN` (OWNER). All operations must succeed identically.

---

## 4. Checklist — Multi-Tenant Isolation

### 4.1 Create a second tenant

```bash
make create-tenant slug=beta email=owner@beta.com
```

### 4.2 Register a user in acme only

```bash
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: acme" \
  -d '{"email":"acme-user@test.com","password":"test123"}' | python3 -m json.tool
# Expected: HTTP 201 with access_token, user_id, email, role: "MEMBER"
```

### 4.3 Confirm user is NOT visible in beta tenant

```bash
BETA_TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -H "X-Tenant-Slug: beta" \
  -d '{"email":"owner@beta.com","password":"changeme123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/users \
  -H "X-Tenant-Slug: beta" \
  -H "Authorization: Bearer $BETA_TOKEN"
```

Expected: the HTML response contains only `owner@beta.com`. `acme-user@test.com` must not appear.

### 4.4 Confirm acme token is rejected by beta

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/users \
  -H "X-Tenant-Slug: beta" \
  -H "Authorization: Bearer $TOKEN"
# Expected: 401 (JWT is scoped to acme, not beta)
```

### 4.5 Health check — known tenant

```bash
curl -s http://localhost:8000/health -H "X-Tenant-Slug: acme"
# Expected: {"status": "ok", "tenant": "acme"}

curl -s http://localhost:8000/health -H "X-Tenant-Slug: beta"
# Expected: {"status": "ok", "tenant": "beta"}
```

### 4.6 Health check — unknown tenant

```bash
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost:8000/health -H "X-Tenant-Slug: unknown-tenant"
# Expected: 404

curl -s http://localhost:8000/health -H "X-Tenant-Slug: unknown-tenant" | python3 -m json.tool
# Expected: {"detail": "Tenant 'unknown-tenant' not found"}
```

### 4.7 Health check — missing header

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health
# Expected: 400

curl -s http://localhost:8000/health | python3 -m json.tool
# Expected: {"detail": "X-Tenant-Slug header required"}
```

### 4.8 Tenant database files are physically separate

```bash
ls -lh data/tenants/
# Expected: acme.db and beta.db as separate files

# acme user count
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tenants/acme.db')
rows = conn.execute('SELECT COUNT(*) FROM user').fetchone()
print('acme users:', rows[0])
conn.close()
"

# beta user count — should be 1 (owner only)
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tenants/beta.db')
rows = conn.execute('SELECT COUNT(*) FROM user').fetchone()
print('beta users:', rows[0])
conn.close()
"
```

---

## 5. Checklist — HTMX Behaviour

All checks in this section require a browser with DevTools open (F12 > Network tab).

### 5.1 POST /users response is HTML, not JSON

1. Login as `admin@acme.com`, navigate to `/users`.
2. Submit the "Add User" form.
3. In DevTools Network, click the `POST /users` request.
4. Check **Response Headers**: `content-type` must be `text/html; charset=utf-8`.
5. Check **Response** tab: raw HTML (a `<tr>` element), not a JSON object.

### 5.2 Form submit triggers no full page reload

1. With DevTools Network open, submit the "Add User" form.
2. Verify: no `GET /users` navigation request follows the POST.
3. Verify: the browser tab favicon does not spin (no full navigation).
4. Verify: the new row appears inline via HTMX swap.

### 5.3 403 error renders inline, not as redirect

1. Login as `member@acme.com`, navigate to `/users`.

   The MEMBER role can view the list but cannot submit the create form directly.

2. Attempt a direct POST via curl to confirm 403:

   ```bash
   curl -s -w "\nHTTP %{http_code}\n" \
     -X POST http://localhost:8000/users \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -H "X-Tenant-Slug: acme" \
     -H "Authorization: Bearer $MEMBER_TOKEN" \
     -d "email=x@acme.com&password=pass&role=VIEWER"
   # Expected: HTTP 403 — no Location header, no redirect
   ```

3. In the browser: if the form is somehow submitted by a MEMBER, the error message must appear inline within the page (no navigation to `/403` or a separate error page).

### 5.4 Delete removes the row without page reload

1. Login as `admin@acme.com`, navigate to `/users`.
2. Click Delete on any row.
3. In DevTools Network: a `DELETE /users/<uuid>` request appears.
4. Status is `200` with an empty response body.
5. The corresponding `<tr>` row is removed from the DOM without a full reload.

---

## 6. SQLite vs PostgreSQL — Known Limitations

| Feature | SQLite (current) | PostgreSQL (production) |
|---|---|---|
| Concurrent writes | Serialized — one writer at a time | Full concurrent writes with row-level locking |
| ALTER TABLE | Requires `render_as_batch=True` in Alembic | Native `ALTER TABLE` without recreation |
| Schema namespacing | Not supported — isolated `.db` files per tenant | `schema=` in `__table_args__`; one database, many schemas |
| JSON columns | Stored as `TEXT`; no indexing | Native `JSONB` with GIN indexes |
| Full-text search | FTS5 extension (limited query syntax) | `pg_trgm`, `tsvector`, `tsearch2` |
| Connection pooling | Not needed (file-local, no network) | PgBouncer recommended at scale |
| Tenant isolation mechanism | Separate `.db` files under `data/tenants/` | Separate PostgreSQL schemas |
| Cross-tenant queries | Not possible (different files) | Technically possible but prohibited by architecture |
| Backup | `cp data/tenants/slug.db backup/` | `pg_dump` per schema or per database |
| WAL / replication | WAL mode available; no streaming replication | Full streaming replication, logical replication |
| Alembic `batch_op` | Required for all column changes | Not required |

When migrating to PostgreSQL:

1. Replace `create_tenant_engine` to use `postgresql+asyncpg://` DSN.
2. Add `schema=<tenant_slug>` to all `SQLModel` `__table_args__`.
3. Remove `render_as_batch=True` from Alembic env files.
4. Update `create-tenant` script to `CREATE SCHEMA <slug>` instead of creating a `.db` file.
5. Update `TenantMiddleware` to resolve tenant from the registry (no change needed in logic).

---

## 7. Reset / Cleanup

Remove all data and start fresh:

```bash
rm -rf data/registry.db data/tenants/
make migrate-registry
make create-tenant slug=acme email=owner@acme.com
```

To reset a single tenant without touching others:

```bash
rm data/tenants/acme.db
make migrate-tenant TENANT_SLUG=acme
uv run python -m scripts.create_tenant --slug acme --email owner@acme.com
# This will fail if acme is still in registry.db.
# Delete the registry row first if re-creating from scratch:
python3 -c "
import sqlite3
conn = sqlite3.connect('data/registry.db')
conn.execute(\"DELETE FROM tenant WHERE slug = 'acme'\")
conn.commit()
conn.close()
print('Removed acme from registry')
"
make create-tenant slug=acme email=owner@acme.com
```
