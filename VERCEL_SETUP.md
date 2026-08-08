# Vercel Production Setup

Your app is currently deployed on Vercel, but the database configuration is incompatible with Vercel's serverless architecture.

## The Problem

SQLite files on Vercel's filesystem are **ephemeral** — they disappear when:
- A new deployment is pushed
- The function instance resets
- You refresh your browser (new request may hit a new instance)

This is why revision desk data resets on refresh in production.

## The Solution: Postgres Database

Vercel supports external databases. Use **Neon** (free tier available):

### Step 1: Create Neon Postgres Database

1. Go to [neon.tech](https://neon.tech) and sign up
2. Create a new project
3. Copy your connection string: `postgresql://user:password@host/dbname`

### Step 2: Configure Vercel Environment

In Vercel dashboard for your project:

1. **Settings** → **Environment Variables**
2. Add these variables:

| Name | Value |
|------|-------|
| `DATABASE_URL` | Your Neon connection string |
| `ANTHROPIC_API_KEY` | Your Claude API key |
| `APP_SECRET` | A strong random string (e.g., 32 random chars) |
| `APP_TIMEZONE` | `Asia/Dubai` |

3. Click **Save**
4. Redeploy from Vercel dashboard

### Step 3: Verify Production

After redeploy:
1. Go to your production URL (https://maznify.com)
2. Login
3. Add/edit revision desk entries
4. **Refresh the browser** → data should persist ✓

## Local Development

Your local `.env` can keep using SQLite:
```
DATABASE_URL=sqlite:///./studymate.db
ANTHROPIC_API_KEY=your-key
```

Production `.env` (in Vercel) uses Postgres:
```
DATABASE_URL=postgresql://...
ANTHROPIC_API_KEY=your-key
APP_SECRET=strong-random-string
```

## Database Migrations

The app automatically runs migrations on startup:
- `Base.metadata.create_all(engine)` — creates all tables
- `apply_lightweight_migrations()` — adds new columns to existing tables

No manual migration needed; just redeploy.

## Uploads Storage

Uploads are still stored locally in `/uploads`. For production, you'll need to:
1. Move uploads to a persistent storage (AWS S3, Vercel Blob Storage, etc.)
2. Update [app/notes.py](app/notes.py) to use the cloud provider

For now, uploaded files won't persist across redeployments. This is separate from the revision desk data issue.

## Troubleshooting

**Still getting 500 errors?**

1. Check Vercel deployment logs:
   - Vercel dashboard → Your project → Deployments → view logs
2. Ensure `DATABASE_URL` is set in Vercel environment variables
3. Verify the Neon connection string is correct

**Lost all data after update?**

Your data is safe in Neon. The seed/migration scripts are idempotent (they only add missing data, never delete). Your study sessions and topics are preserved.

**Stuck?**

Share your Vercel deployment error logs and we can debug from there.
