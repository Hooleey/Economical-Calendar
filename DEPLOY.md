# Production Deploy

This project is split deploy:

- Frontend (React/Vite): GitHub Pages
- Backend (FastAPI): Render

## 1) Backend on Render

1. Open Render and create **Blueprint** from this repository.
2. Render will detect `render.yaml` and create service `economic-calendarr-api`.
3. Wait for deploy completion, then copy backend URL, for example:
   - `https://economic-calendarr-api.onrender.com`
4. In Render service env vars set:
   - `FRONTEND_ORIGIN_REGEX=^https://hooleey\.github\.io$`
   - Optional: `ALFAFOREX_SYNC_TTL_SECONDS`, `NEWS_SYNC_TTL_SECONDS`.

## 2) Frontend on GitHub Pages

1. In GitHub repository settings:
   - **Settings -> Environments/Secrets and variables -> Actions -> Variables**
   - Add variable: `VITE_API_BASE`
   - Value: your Render backend URL, e.g. `https://economic-calendarr-api.onrender.com`
2. Push to `main` or run workflow manually:
   - `.github/workflows/deploy-pages.yml`
3. Open Pages URL:
   - `https://hooleey.github.io/economicCalendarr/`

## 3) Quick checks

- Backend health: `<render-url>/health`
- Frontend loads: Pages URL returns app
- News list and news reading page work without CORS errors
