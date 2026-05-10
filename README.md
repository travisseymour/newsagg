# NewsAgg

A self-hosted RSS news aggregator — similar to the TechURLs Website.

## Local Setup

```bash
pip install -r requirements.txt
python scraper.py   # prime the cache first
python app.py       # start Flask dev server at http://localhost:5000
```

The app automatically fetches feeds when you visit if the cache is empty or older than 1 hour. Click the refresh button to manually update anytime.

## Customizing Sources

Edit `sources.yaml` to add, remove, or toggle sources.
Each entry has:

```yaml
- name: Hacker News # display name
  url: https://... # RSS or Atom feed URL
  enabled: true # false = skipped by scraper and hidden from feed
  category: tech # tech | dev | science | other (informational)
```

## Admin Panel

Visit `/admin` in your browser. Default password: `changeme`.

Set a real password via environment variable:

```bash
export NEWSAGG_ADMIN_PASSWORD="your_secret"
```

The admin panel lets you:

- Toggle sources on/off with a visual switch
- Add new RSS sources
- Delete sources (removes cache too)

## Railway Deployment

1. **Push to GitHub** — Railway deploys from your repo

2. **Create a new project** on [railway.com](https://railway.com):

   - New Project → Deploy from GitHub repo
   - Select your newsagg repository

3. **Set environment variables** (Variables tab):

   ```
   NEWSAGG_ADMIN_PASSWORD = your_secret_password
   ```

4. **Deploy** — Railway auto-detects Python and uses the `railway.toml` config

The app will automatically refresh feeds when visitors arrive if the cache is older than 1 hour.

## API

- `GET /api/feeds` — returns all cached feed data as JSON
- `POST /api/scrape` — triggers a background refresh
- `GET /api/scrape/status` — check if a scrape is running

## Project Structure

```
newsagg/
├── app.py                  # Flask app + routes
├── scraper.py              # RSS fetcher, writes to cache/
├── sources.yaml            # Your list of feeds (edit this!)
├── requirements.txt
├── railway.toml            # Railway deployment config
├── templates/
│   ├── index.html          # Main feed view
│   └── admin.html          # Admin panel
└── cache/                  # Auto-created; JSON per source + _manifest.json
```
