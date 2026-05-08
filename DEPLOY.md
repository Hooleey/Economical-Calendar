# Production Deploy

This project is split deploy:

- Frontend (React/Vite): GitHub Pages
- Backend (FastAPI): Render

## 1) Backend on Render

1. Откройте Render → **Blueprint** или подключите **GitHub repo** для Web Service из папки `backend` по `render.yaml`.
2. Дождитесь деплоя, скопируйте URL API (ваш может быть например  
   `https://economical-calendar.onrender.com`).
3. Обязательно задайте в **Environment** сервиса:
   - **`DATABASE_URL`** — строка подключения Neon `postgresql://...?sslmode=require`.
   - **`FRED_API_KEY`** — ключ FRED (резервные события и режим «точная дата» без AlfaForex).
   - **`FRONTEND_ORIGIN_REGEX`** — например `^https://hooleey\.github\.io$` или шире под все `*.github.io`,  
     либо **`FRONTEND_ORIGINS`** через запятую, например `https://hooleey.github.io`.
   - По желанию: `FORCE_STARTUP_SYNC=true` если нужно снова тянуть весь Alfa/news на каждой перезагрузке воркера (на Render часто тормозит).

После каждого `git push` в трекинг‑ветку Render сам пересоберёт сервис (**autoDeploy**). Проверьте  
`GET <api>/health` — ожидаются поля **`version`** (минимум **0.6.0** после обновления кода), **`fred_api_configured`**, **`features.news`**.

Если `DATABASE_URL` не задан, backend использует локальный **SQLite** (`events.db`).

## 2) Frontend on GitHub Pages

1. In GitHub repository settings:
   - **Settings -> Environments/Secrets and variables -> Actions -> Variables**
   - Add variable: `VITE_API_BASE`
   - Value: полный HTTPS URL вашего API, например `https://economical-calendar.onrender.com` (без `/` на конце)
2. Push to `main` or run workflow manually:
   - `.github/workflows/deploy-pages.yml`
3. Open Pages URL (подставьте имя репозитория):
   - `https://hooleey.github.io/Economical-Calendar/` (может быть в нижнем регистре в URL GitHub Pages)

## 3) Quick checks

- Backend: `<render-url>/health` → `"status":"ok"`, есть **`fred_api_configured`** и версия **`0.6.0+`**
- Если в `/health` всё ещё **старая версия** (например `0.5.0`) — на Render выполните **Manual deploy** из актуальной ветки или проверьте, что деплится тот же репозиторий/ветка что и ваш локальный проект.
- Фронт: Pages открывается, в DevTools запросы к API идут на Render, ошибок **CORS** нет.
