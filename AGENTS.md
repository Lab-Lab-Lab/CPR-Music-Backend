# AGENTS.md - MusicCPR Backend

## Project Overview

MusicCPR is a music education learning management system. This is the Django REST API backend, built with Cookiecutter Django.

## Tech Stack

- **Framework**: Django with Django REST Framework
- **Database**: PostgreSQL (configured via `DATABASE_URL` env var)
- **Auth**: django-allauth + DRF token auth
- **API Docs**: drf-spectacular (Swagger at `/api/schema/swagger-ui/`)
- **Code Style**: Black, isort, flake8 (configured in `setup.cfg` and `.pre-commit-config.yaml`)
- **Testing**: pytest with `--ds=config.settings.test --reuse-db`
- **Deployment**: Railway (and legacy EC2/supervisor)

## Project Structure

```
config/                  # Django project config
  settings/              # Split settings: base, local, production, test, railway
  urls.py                # Root URL config
  api_router.py          # DRF router with nested routes
  websocket.py           # WebSocket config

teleband/                # Main application package
  users/                 # Custom user model, auth tokens
  courses/               # Courses, enrollments
  assignments/           # Assignments, activities, piece plans
  submissions/           # Submissions, grades, attachments, activity progress
  musics/                # Pieces (musical works)
  instruments/           # Instruments
  dashboards/            # Research dashboards
  utils/                 # Shared serializers/utilities
```

## API Structure

The API uses nested DRF routers:
- `/api/courses/{slug}/assignments/` - assignments within a course
- `/api/courses/{slug}/assignments/{id}/submissions/` - submissions for an assignment
- `/api/courses/{slug}/assignments/{id}/submissions/{id}/attachments/` - attachments on a submission
- `/api/courses/{slug}/activities/` - activities in a course
- `/api/courses/{slug}/grades/` - grades in a course
- `/api/courses/{slug}/submissions/` - teacher view of submissions
- `/api/users/`, `/api/enrollments/`, `/api/pieces/`, `/api/instruments/`, `/api/configs/`

## Key Commands

```bash
# Activate virtual environment
source .venv/bin/activate

# Run tests
pytest

# Run dev server
python manage.py runserver

# Migrations
python manage.py makemigrations
python manage.py migrate

# Type checking
mypy teleband
```

## Conventions

- Settings are split across `config/settings/` - use `base.py` for shared config
- App-specific API code lives in `<app>/api/views.py` and `<app>/api/serializers.py`
- Pre-commit hooks enforce Black formatting, isort import ordering, and flake8 linting
- Migrations are excluded from linting (`exclude: "^docs/|/migrations/"`)
- Environment config via `.env` file (read automatically when `DJANGO_READ_DOT_ENV_FILE=True`)
