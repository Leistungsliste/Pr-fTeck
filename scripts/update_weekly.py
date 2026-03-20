name: Update Prüftechniker Weekly RSS

on:
  schedule:
    - cron: "0 7 * * 1"
  workflow_dispatch:

permissions:
  contents: write

jobs:
  build-weekly-rss:
    runs-on: ubuntu-latest

    env:
      FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

    steps:
      - name: Repository auschecken
        uses: actions/checkout@v4

      - name: Python einrichten
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Abhängigkeiten installieren
        run: |
          python -m pip install --upgrade pip
          pip install requests feedparser beautifulsoup4 lxml

      - name: Weekly RSS erzeugen
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: python scripts/update_weekly_ai.py

      - name: Änderungen committen und pushen
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add prueftechniker-weekly.xml weekly-data.json
          git diff --cached --quiet || git commit -m "Automatisches KI-Weekly Update"
          git push
