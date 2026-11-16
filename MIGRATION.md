# Moving to Supabase Postgres + Cloudflare R2

Everything is driven by environment variables, so the code is already ready for
both. Nothing changes until you fill in `.env`:

| Variable unset | Behaviour |
| --- | --- |
| `DATABASE_URL` | uses the local `db.sqlite3` |
| `R2_BUCKET_NAME` | uploads go to `./media` on local disk |

`.env.example` documents every setting. Start with `cp .env.example .env`.

---

## 1. Database: SQLite to Supabase

### Get the right connection string

In the Supabase dashboard: **Project Settings -> Database -> Connection
string -> Session pooler**. It looks like:

```
postgresql://postgres.abcdefghijkl:PASSWORD@aws-0-eu-central-1.pooler.supabase.com:5432/postgres
```

Two strings in that dashboard will not work, and the failure modes are
confusing:

- **`db.<project-ref>.supabase.co:5432`** (the "direct connection") resolves to
  **IPv6 only** unless you pay for the IPv4 add-on. Most hosts are IPv4-only, so
  this fails with a connection timeout that looks like a firewall problem.
- **port `6543`** is **transaction mode**. It has no prepared statements, no
  temporary tables and no `LISTEN`/`NOTIFY`, so `migrate` fails partway through
  and leaves the schema half-built.

Use the pooler host on **port 5432** (session mode), with the
`postgres.<project-ref>` username. URL-encode any special characters in the
password: `@` becomes `%40`, `:` becomes `%3A`, `/` becomes `%2F`.

### Transfer the data

```bash
# 1. Export, while DATABASE_URL is still unset so this reads SQLite
python manage.py transfer_data dump

# 2. Put the pooler URL in DATABASE_URL in .env, then
python manage.py transfer_data load
```

`load` runs `migrate`, then `loaddata`, then resets every Postgres sequence.
That last step matters: `loaddata` inserts explicit primary keys without
advancing the sequences, so without it the next record you create through the
app raises `IntegrityError: duplicate key value`.

The export deliberately skips `contenttypes`, `auth.Permission`,
`admin.logentry`, sessions and the JWT blacklist. The first two are rebuilt by
`migrate`; copying them causes primary-key collisions. Password hashes do carry
over, so existing logins keep working.

Verify:

```bash
python manage.py shell -c "from crouirouge.models import User; print(User.objects.count())"
```

The current SQLite database holds 92 rows, 35 of them users.

---

## 2. Media files: local disk to R2

### Create the bucket

1. Cloudflare dashboard -> **R2** -> create a bucket.
2. **Manage R2 API Tokens** -> create a token with *Object Read & Write*,
   scoped to that bucket.
3. Give the bucket a public hostname, either a **custom domain**
   (`media.yourdomain.com`) or by enabling its **r2.dev** public URL.
   Without one, Django falls back to signed URLs that expire.

Fill in `R2_BUCKET_NAME`, `R2_ENDPOINT_URL`
(`https://<ACCOUNT_ID>.r2.cloudflarestorage.com`), `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY` and `R2_CUSTOM_DOMAIN`.

### Upload

```bash
python manage.py upload_media_to_r2 --dry-run   # 68 files, ~16 MB
python manage.py upload_media_to_r2
```

Object keys match the paths already stored in the database
(`profile_images/avatar.png`), so **no database rows need changing**. The
command skips keys that already exist, so it is safe to re-run; add
`--overwrite` to force re-upload.

The duplicate `activity_images/`, `profile_images/` etc. folders at the project
root are leftovers from before `MEDIA_ROOT` pointed at `media/`, and are not
served today. `--include-legacy` uploads anything from them that `media/` does
not already provide.

### Two R2 quirks the code already handles

- **No ACLs.** R2 rejects `ACL` headers outright, so `default_acl` is left
  unset. Public access comes from the bucket's custom domain, not from
  per-object ACLs.
- **boto3 checksums.** boto3 >= 1.36 attaches CRC32 checksums to uploads, which
  R2 rejects with `Header 'x-amz-checksum-crc32' not implemented`. `settings.py`
  sets `AWS_REQUEST_CHECKSUM_CALCULATION=when_required` to avoid this. If you
  ever see that error, that setting is why.

### Static files stay local

Only *media* moves to R2. `ProofOfRegistrationView` and
`download_single_user_info` both read `STATIC_ROOT/logo.png` off the filesystem
with `open()`, so moving static files to object storage breaks PDF generation.
Keep serving static from the host (`collectstatic` + the host's static mapping,
or WhiteNoise).

---

## 3. Before going live

Set these in the host's environment (not in a committed `.env`):

```bash
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=<generate a new one>
DJANGO_ALLOWED_HOSTS=yourdomain.com
DJANGO_CORS_ALLOWED_ORIGINS=https://your-frontend.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://your-frontend.com
```

Generate the key with:

```bash
python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

With `DEBUG=False` the project automatically switches to HTTPS redirects,
`Secure` cookies, `nosniff`, `X-Frame-Options: DENY`, origin-restricted CORS,
and staff-only API docs. Confirm with:

```bash
python manage.py check --deploy
```

HSTS is intentionally off by default because it is hard to reverse — browsers
honour it for its full duration. Turn it on once HTTPS is confirmed working:
`DJANGO_HSTS_SECONDS=31536000`.

### Still outstanding

- **Rotate the Gmail app password.** It was committed in `settings.py` in plain
  text, so treat it as public: <https://myaccount.google.com/apppasswords>.
  The old `SECRET_KEY` is likewise compromised and must not be reused.
- **`/api/download_single_user_info/<id>/` is unauthenticated**, and serves a
  PDF containing a member's national ID and home address. Anyone can enumerate
  integers. This predates the current work and should be locked down.
- **The newsletter send is synchronous**, looping over subscribers inside the
  request. With a real subscriber list it will exceed the request timeout; move
  it to a scheduled task or background job.
- **Supabase free tier** pauses a project after 7 days of inactivity and caps
  the database at 500 MB.
