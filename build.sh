#!/usr/bin/env bash
# Render runs this on every deploy, before starting the web process.
# Exit immediately if any step fails, so a broken build never goes live.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

# Collect static files for WhiteNoise to serve. Includes logo.png, which the
# two PDF views read off disk.
python manage.py collectstatic --no-input

# Apply any new migrations to Supabase. Safe to run on every deploy: Django
# skips migrations that are already applied.
python manage.py migrate
