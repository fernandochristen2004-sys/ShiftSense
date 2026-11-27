# Deploying ShiftSense (free tier)

Three free services, one per part:

| Part | Host | What it runs |
|---|---|---|
| Database | **Neon** | PostgreSQL |
| API | **Render** | `Dockerfile`: migrations, then FastAPI and the solver |
| Dashboard | **Vercel** | `web/` (Next.js), which proxies `/api` to Render |

The browser only ever talks to Vercel. Vercel forwards `/api/...` to Render,
so the login cookie belongs to one site and stays `SameSite=Lax`.

Free-tier trade-offs: Render's free API sleeps after 15 minutes without
visitors and takes about a minute to wake, and it has a small CPU share, so
the solver is slower than on your laptop. Switching the Render service to a
paid instance type removes both, with no code changes.

## 1. Database: Neon

1. Sign up at neon.com and create a project (any region near you, Postgres 18).
2. On the project dashboard, click **Connect**, turn **Connection pooling off**,
   and copy the connection string. It looks like
   `postgresql://user:password@ep-....neon.tech/neondb?sslmode=require&channel_binding=require`.
   Keep it secret: it's the key to your data.

## 2. API: Render

1. Sign up at render.com with your GitHub account.
2. **New → Web Service**, pick the ShiftSense repository.
3. Settings:
   - **Language / Runtime:** Docker (it finds the `Dockerfile`)
   - **Branch:** `main`
   - **Instance type:** Free
   - **Health check path:** `/health`
4. **Environment variables:**

   | Name | Value |
   |---|---|
   | `SHIFTSENSE_DATABASE_URL` | the Neon connection string, pasted as-is |
   | `SHIFTSENSE_SECURE_COOKIES` | `true` |

5. **Deploy.** The first build takes a few minutes. When it's live, open
   `https://<your-service>.onrender.com/health`: it should say `{"status":"ok"}`.
   Note the address for the next step.

## 3. Dashboard: Vercel

1. Sign up at vercel.com with your GitHub account.
2. **Add New → Project**, import the ShiftSense repository.
3. Settings:
   - **Root Directory:** `web`
   - **Framework:** Next.js (detected)
4. **Environment variable:**

   | Name | Value |
   |---|---|
   | `SHIFTSENSE_API_URL` | `https://<your-service>.onrender.com` (no trailing slash) |

5. **Deploy.** Vercel gives you an address like `https://shiftsense.vercel.app`.

## 4. Check it

1. Open the Vercel address. You should see the login box.
2. Click **Try the demo, no account needed**. The first click after the API
   has been asleep can take about a minute; after that it's quick.
3. Sign up, set up a restaurant, log out and back in.

## After that

- Every push to `main` redeploys both (once CI is green is a good habit).
- Old guest accounts (over a week) and their demos are cleared each time a
  new guest starts, so the free database doesn't fill up.
- To make the API always on and faster: Render → your service → **Settings →
  Instance type → Starter**. Switch back to Free the same way.
