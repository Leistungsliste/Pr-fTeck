import json
import os
import re
import html
import sys
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime

import feedparser
import requests
from bs4 import BeautifulSoup


REPO_BASE_URL = "https://leistungsliste.github.io/Pr-tleck"
OUTPUT_XML = Path("prueftechniker-weekly.xml")
OUTPUT_JSON = Path("weekly-data.json")

OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = "gpt-4.1-mini"

USER_AGENT = "Mozilla/5.0 (compatible; PrueftechnikerWeeklyBot/1.0)"

SOURCES = [
    {
        "name": "DGUV Publikationen",
        "feed_url": "https://publikationen.dguv.de/rss.xml",
        "category": "normen",
        "fallback_url": "https://publikationen.dguv.de/",
        "max_items": 3,
    },
    {
        "name": "BAuA Presse",
        "feed_url": "https://www.baua.de/DE/Service/Presse/rss.xml",
        "category": "normen",
        "fallback_url": "https://www.baua.de/DE/Service/Presse/Presse.html",
        "max_items": 3,
    },
    {
        "name": "VDE News",
        "feed_url": "https://www.vde.com/de/rss-news",
        "category": "normen",
        "fallback_url": "https://www.vde.com/de",
        "max_items": 3,
    },
    {
        "name": "Fluke Blog",
        "feed_url": "https://www.fluke.com/en/learn/blog/rss",
        "category": "geraete",
        "fallback_url": "https://www.fluke.com/en/learn/blog",
        "max_items": 2,
    },
]

STATIC_PRACTICE_HINTS = [
    "Für Prüftechniker sind vor allem Änderungen mit Auswirkung auf Prüffristen, Dokumentation, Normenumstellungen und Gerätesoftware relevant.",
    "Herstellerquellen sind nützlich für Gerätefunktionen und Softwarestände, offizielle Quellen bleiben aber maßgeblich für die fachliche Einordnung.",
    "Neue Beiträge sollten darauf geprüft werden, ob sie OVV, ortsfeste Anlagen, Maschinenprüfung oder nur Produktmarketing betreffen.",
]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def safe_text(text: str) -> str:
    return html.escape((text or "").strip(), quote=True)


def strip_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def truncate(text: str, max_len: int = 1600) -> str:
    text = (text or "").strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def fetch_page_excerpt(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return truncate(strip_html(response.text), 1600)
    except Exception as exc:
        return f"Seite konnte nicht geladen werden: {exc}"


def parse_feed(source: dict) -> list[dict]:
    parsed = feedparser.parse(source["feed_url"])
    items = []

    for entry in parsed.entries[: source["max_items"]]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or source["fallback_url"]).strip()
        summary = strip_html(entry.get("summary") or entry.get("description") or "")

        published = ""
        if entry.get("published_parsed"):
            try:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                published = dt.date().isoformat()
            except Exception:
                published = ""

        if title:
            items.append(
                {
                    "source": source["name"],
                    "category": source["category"],
                    "title": title,
                    "link": link,
                    "summary": truncate(summary, 900),
                    "published": published,
                    "page_excerpt": fetch_page_excerpt(link),
                }
            )

    return items


def collect_items() -> list[dict]:
    collected = []

    for source in SOURCES:
        try:
            source_items = parse_feed(source)
            print(f"[INFO] {source['name']}: {len(source_items)} Einträge gesammelt")
            collected.extend(source_items)
        except Exception as exc:
            print(f"[WARN] Feed-Laden fehlgeschlagen: {source['name']} -> {exc}")
            collected.append(
                {
                    "source": source["name"],
                    "category": source["category"],
                    "title": f"Quelle konnte nicht geladen werden: {source['name']}",
                    "link": source["fallback_url"],
                    "summary": f"Automatischer Hinweis: Feed-Laden fehlgeschlagen ({exc}).",
                    "published": "",
                    "page_excerpt": "",
                }
            )

    return collected


def build_ai_prompt(items: list[dict]) -> str:
    lines = []
    lines.append("Erstelle ein deutsches Weekly für Prüftechniker.")
    lines.append("Zielgruppe: Prüftechniker für elektrische Prüfungen, Betriebsmittel, Anlagen, Normenumfeld.")
    lines.append("Wichtig: Keine erfundenen Fakten. Nur vorsichtige, nützliche Formulierungen.")
    lines.append("Wenn Informationen unklar sind, formuliere zurückhaltend.")
    lines.append("")
    lines.append("Ausgabeformat:")
    lines.append("- Reines HTML")
    lines.append("- Kein Markdown")
    lines.append("- Nutze genau diese Struktur:")
    lines.append("  <h3>Prüftechniker Weekly</h3>")
    lines.append("  <p>Kurze Einleitung</p>")
    lines.append("  <h4>Offizielle Quellen / Normen / Regeln</h4><ul>...</ul>")
    lines.append("  <h4>Messgeräte / Hersteller</h4><ul>...</ul>")
    lines.append("  <h4>Praxisrelevanz</h4><ul>...</ul>")
    lines.append("  <h4>Quellen</h4><ul>...</ul>")
    lines.append("")
    lines.append("Praxis-Hinweise, die berücksichtigt werden sollen:")
    for hint in STATIC_PRACTICE_HINTS:
        lines.append(f"- {hint}")
    lines.append("")
    lines.append("Hier sind die gesammelten Quellen:")
    lines.append("")

    for idx, item in enumerate(items, start=1):
        lines.append(f"Quelle {idx}")
        lines.append(f"Quelle-Name: {item['source']}")
        lines.append(f"Kategorie: {item['category']}")
        lines.append(f"Titel: {item['title']}")
        lines.append(f"Link: {item['link']}")
        lines.append(f"Veröffentlicht: {item['published']}")
        lines.append(f"Feed-Zusammenfassung: {item['summary']}")
        lines.append(f"Seitenauszug: {item['page_excerpt']}")
        lines.append("")

    return "\n".join(lines)


def call_openai(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY fehlt oder ist leer.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Du bist ein Fachredakteur für Prüftechniker. "
                    "Schreibe präzise, vorsichtig, hilfreich und ohne Halluzinationen. "
                    "Nutze nur die bereitgestellten Informationen und liefere HTML."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.3,
    }

    print("[INFO] Sende Anfrage an OpenAI ...")

    response = requests.post(
        OPENAI_CHAT_URL,
        headers=headers,
        json=payload,
        timeout=120,
    )

    print(f"[INFO] OpenAI HTTP-Status: {response.status_code}")

    if response.status_code != 200:
        body_preview = response.text[:2000]
        raise RuntimeError(f"OpenAI API Fehler {response.status_code}: {body_preview}")

    data = response.json()

    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"Unerwartete API-Antwort: {json.dumps(data)[:2000]}")

    if not text or not text.strip():
        raise RuntimeError("Keine Textausgabe von der OpenAI API erhalten.")

    print("[INFO] KI-Zusammenfassung erfolgreich erzeugt.")
    return text.strip()


def build_fallback_html(items: list[dict], reason: str) -> str:
    blocks = [
        "<h3>Prüftechniker Weekly</h3>",
        "<p>Die KI-Zusammenfassung konnte diesmal nicht erzeugt werden. Unten findest du trotzdem die automatisch gesammelten Quellenlinks.</p>",
        f"<p><b>Fehler:</b> {safe_text(reason)}</p>",
        "<h4>Quellen</h4>",
        "<ul>",
    ]

    for item in items:
        title = safe_text(item["title"])
        source = safe_text(item["source"])
        link = safe_text(item["link"])
        blocks.append(f'<li><a href="{link}">{title}</a> – {source}</li>')

    blocks.append("</ul>")
    return "\n".join(blocks)


def build_xml(html_description: str, generated: datetime) -> str:
    pub_date = format_datetime(generated)
    guid = f"prueftechniker-weekly-{generated.strftime('%Y-%m-%d-%H%M%S')}"
    title = f"Prüftechniker Weekly – {generated.strftime('%d.%m.%Y')}"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Prüftechniker Weekly Update</title>
    <link>{REPO_BASE_URL}/prueftechniker-weekly.xml</link>
    <description>Automatisch erzeugtes Weekly mit KI-Zusammenfassung zu VDE, DGUV, TRBS, Prüfpraxis, Messgeräten und Software.</description>
    <language>de-de</language>
    <lastBuildDate>{pub_date}</lastBuildDate>
    <ttl>10080</ttl>

    <item>
      <title>{safe_text(title)}</title>
      <link>{REPO_BASE_URL}/</link>
      <guid>{guid}</guid>
      <pubDate>{pub_date}</pubDate>
      <description><![CDATA[
{html_description}
      ]]></description>
    </item>
  </channel>
</rss>
"""


def main():
    generated = now_utc()
    items = collect_items()
    prompt = build_ai_prompt(items)

    status = "ok"
    error_message = ""

    try:
        ai_html = call_openai(prompt)
    except Exception as exc:
        error_message = str(exc)
        print(f"[ERROR] KI-Zusammenfassung fehlgeschlagen: {error_message}", file=sys.stderr)
        ai_html = build_fallback_html(items, error_message)
        status = f"fallback: {error_message}"

    xml = build_xml(ai_html, generated)

    OUTPUT_XML.write_text(xml, encoding="utf-8")
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": generated.isoformat(),
                "status": status,
                "error": error_message,
                "model": OPENAI_MODEL,
                "items": items,
                "html_preview": ai_html,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"[INFO] weekly-data.json geschrieben, Status: {status}")
    print("[INFO] prueftechniker-weekly.xml aktualisiert")


if __name__ == "__main__":
    main()
