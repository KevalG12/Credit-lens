# Deploying CreditLens

You do **not** need to deploy to run the project: `uvicorn app.main:app` serves the API and the
website together on http://localhost:8000. Deploy only to give judges a public link.

The app is one container (FastAPI serves the static frontend too), so any host that runs a
Dockerfile works. The container needs three environment variables:

| Variable | Value |
|---|---|
| `CREDITLENS_ENV` | `production` (refuses to start with the insecure default secret) |
| `CREDITLENS_JWT_SECRET` | a long random string (`python -c "import secrets;print(secrets.token_hex(32))"`) |
| `CREDITLENS_DATABASE_URL` | your Neon connection string (keeps users and scores forever, see below). Without it the app falls back to a local SQLite file, which a free host wipes on restart |

## Keep users and scores permanently: Neon (free PostgreSQL)
Free hosts erase their local disk on every restart, so accounts and past scores need an external database.
The app switches to PostgreSQL automatically when `CREDITLENS_DATABASE_URL` (or `DATABASE_URL`) is set;
the tables are created on first start. Locally, with nothing set, it keeps using the `creditlens.db` file.

1. Sign up at neon.tech (GitHub login works) and click **Create project** (any name, nearest region).
2. On the project dashboard click **Connect**, make sure **Pooled connection** is on, and copy the connection string.
   It looks like `postgresql://USER:PASSWORD@ep-xxxx-pooler.REGION.aws.neon.tech/neondb?sslmode=require`.
3. Paste it as `CREDITLENS_DATABASE_URL` in your host's environment settings (Render: service > Environment).
4. Redeploy. Register a user, restart the service, and sign in again: the account is still there.
5. Optional: Neon's SQL Editor shows the `users` and `scores` tables. Passwords are stored only as PBKDF2 hashes and
   raw statements are never stored.

Neon's free database pauses when idle, so the first request after a quiet period can take a second or two.
Never commit the connection string to GitHub; keep it only in the host's environment settings.

To test the Postgres code yourself: `CREDITLENS_TEST_PG_URL=<scratch db url> python -m unittest tests.test_postgres`
(it drops the `users`/`scores` tables in that database, so use a scratch Neon branch).

## Staying signed in
Logins last 7 days by default (`CREDITLENS_JWT_MINUTES=10080`) and the browser keeps the token between visits.
"Sign out" clears it. On a shared computer, press Sign out when finished.

## Option A: Render (easiest, uses `render.yaml`)
1. Push this folder to a GitHub repository.
2. Render dashboard > **New > Blueprint** > select the repo. It reads `render.yaml`.
3. Wait for the build; you get `https://creditlens-xxxx.onrender.com`.
Free instances sleep when idle, so open the link a minute before presenting. Your data is safe in Neon either way.

## Option B: Railway / Fly.io
* **Railway:** New Project > Deploy from GitHub repo (it detects the Dockerfile). Add the variables above.
* **Fly.io:** `fly launch` (accept the Dockerfile), then `fly secrets set CREDITLENS_JWT_SECRET=... CREDITLENS_DATABASE_URL=...`
  and `fly deploy`.

## Option C: your own machine, public link for a few hours
Run the app locally, then expose it with a tunnel such as `cloudflared tunnel --url http://localhost:8000`
or `ngrok http 8000`. No account data leaves your machine except through the tunnel.

## Run the container locally
```
docker build -t creditlens .
docker run -p 8000:8000 -e CREDITLENS_JWT_SECRET=$(python -c "import secrets;print(secrets.token_hex(32))") -e CREDITLENS_DATABASE_URL=<your neon url> creditlens
```

## Before demo day checklist
* Open the public URL on your phone and on a laptop; click **Try the demo**.
* Score one demo file end to end, then open the what-if sliders.
* Keep a backup: the app running locally plus the screen recording.
* Worker count: the auth rate limiter is per process; stay at 1 worker (the default) for the demo.

## GitHub Pages (github.io link) + separate backend
GitHub Pages hosts only static files, so it can serve the **frontend**, not the Python backend.
Run the backend somewhere else (Option A/B above) and point the Pages site at it:

1. Deploy the backend (e.g. Render) and note its URL, such as `https://creditlens.onrender.com`.
2. Allow your Pages origin on the backend: set the env var
   `CREDITLENS_CORS_ORIGINS=https://YOUR-USERNAME.github.io` (comma-separate several origins).
   Use the origin only, with no repo name or trailing slash.
3. Edit `frontend/config.js`: `window.CREDITLENS_API = "https://creditlens.onrender.com";`
4. Push the project to GitHub (repo root = this folder, branch `main`).
5. Repo **Settings > Pages > Source: GitHub Actions**. The included workflow
   (`.github/workflows/pages.yml`) publishes `frontend/`.
6. Your site is live at `https://YOUR-USERNAME.github.io/REPO-NAME/` after the Action finishes (about a minute).

Notes: use the Pages link for the pitch and the backend link only for the API. A free Render backend sleeps when
idle, so open the site once before presenting. Browsers require HTTPS for both sides, which both hosts provide.
