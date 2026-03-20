import json
import os
import re
import html
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime

import feedparser
import requests
from bs4 import BeautifulSoup


REPO_BASE_URL = "https://leistungsliste.github.io/Pr-tleck"
OUTPUT_XML = Path("prueftechniker-weekly.xml")
OUTPUT_JSON = Path("weekly-data.json")
OPENAI_API_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-5.4"

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

STATIC_FALLBACK_SUMMARY = """<h3>Prüftechniker Weekly</h3>
<p>Die KI-Zusammenfassung konnte diesmal nicht erzeugt werden. Unten findest du trotzdem die automatisch gesammelten Quellenlinks.</p>
"""

USER_AGENT = "Mozilla/5.0 (compatible; PrueftechnikerWeeklyBot/1.0)"


def now_utc():
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
        text = strip_html(response.text)
        return truncate(text, 1600)
    except Exception as exc:
        return f"Seite konnte nicht geladen werden: {exc}"


def parse_feed(source: dict) -> list:
    parsed = feedparser.parse(source["feed_url"])
    items = []

    for entry in parsed.entries[: source["max_items"]]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or source["fallback_url"]).strip()
        summary = strip_html(
            entry.get("summary")
            or entry.get("description")
            or ""
        )
        published = ""
        if entry.get("published_parsed"):
            try:
                dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                published = dt.date().isoformat()
            except Exception:
                published = ""

        if title:
            items.append({
                "source": source["name"],
                "category": source["category"],
                "title": title,
                "link": link,
                "summary": truncate(summary, 900),
                "published": published,
                "page_excerpt": fetch_page_excerpt(link),
            })

    return items


def collect_items() -> list:
    collected = []
    for source in SOURCES:
        try:
            collected.extend(parse_feed(source))
        except Exception as exc:
            collected.append({
                "source": source["name"],
                "category": source["category"],
                "title": f"Quelle konnte nicht geladen werden: {source['name']}",
                "link": source["fallback_url"],
                "summary": f"Automatischer Hinweis: Feed-Laden fehlgeschlagen ({exc}).",
                "published": "",
                "page_excerpt": "",
            })
    return collected


def build_ai_prompt(items: list) -> str:
    lines = []
    lines.append(
        "Erstelle ein deutsches, fachlich vorsichtig formuliertes Weekly für Prüftechniker."
    )
    lines.append(
        "Zielgruppe: Prüftechniker für elektrische Prüfungen, Betriebsmittel, Anlagen, Normenumfeld."
    )
    lines.append(
        "Wichtig: Keine erfundenen Fakten. Wenn etwas unklar ist, als Hinweis oder Tendenz formulieren."
    )
    lines.append(
        "Struktur in HTML:"
    )
    lines.append(
        "1. <h3>Prüftechniker Weekly</h3>"
    )
    lines.append(
        "2. Kurze Einleitung als <p>"
    )
    lines.append(
        "3. <h4>Offizielle Quellen / Normen / Regeln</h4> mit <ul><li>...</li></ul>"
    )
    lines.append(
        "4. <h4>Messgeräte / Hersteller</h4> mit <ul><li>...</li></ul>"
    )
    lines.append(
        "5. <h4>Praxisrelevanz</h4> mit <ul><li>...</li></ul>"
    )
    lines.append(
        "6. <h4>Quellen</h4> mit <ul><li><a href='...'>Titel</a> – Quelle</li></ul>"
    )
    lines.append(
        "Bitte nur kompaktes HTML ohne Markdown."
    )
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
        raise RuntimeError("OPENAI_API_KEY fehlt.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "Du bist ein Fachredakteur für Prüftechniker. "
                            "Erstelle vorsichtige, nützliche, gut strukturierte HTML-Zusammenfassungen "
                            "ohne erfundene Details."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    }
                ],
            },
        ],
        "text": {
            "verbosity": "medium"
        }
    }

    response = requests.post(
        OPENAI_API_URL,
        headers=headers,
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    output_text = ""
    for item in data.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    output_text += content.get("text", "")

    output_text = output_text.strip()
    if not output_text:
        raise RuntimeError("Keine Textausgabe von der OpenAI API erhalten.")
    return output_text


def build_fallback_html(items: list) -> str:
    blocks = [STATIC_FALLBACK_SUMMARY, "<h4>Quellen</h4><ul>"]
    for item in items:
        title = safe_text(item["title"])
        source = safe_text(item["source"])
        link = safe_text(item["link"])
        blocks.append(f"<li><a href=\"{link}\">{title}</a> – {source}</li>")
    blocks.append("</ul>")
    return "\n".join(blocks)


def build_xml(html_description: str, generated: datetime) -> str:
    pub_date = format_datetime(generated)
    guid = f"prueftechniker-weekly-{generated.strftime('%Y-%m-%d')}"
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

    try:
      ai_html = call_openai(prompt)
      status = "ok"
    except Exception as exc:
      ai_html = build_fallback_html(items)
      status = f"fallback: {exc}"

    xml = build_xml(ai_html, generated)

    OUTPUT_XML.write_text(xml, encoding="utf-8")
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": generated.isoformat(),
                "status": status,
                "model": OPENAI_MODEL,
                "items": items,
                "html_preview": ai_html,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
