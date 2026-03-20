import json
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

USER_AGENT = "Mozilla/5.0 (compatible; PrueftechnikerWeeklyBot/2.0)"

SOURCES = [
    {
        "name": "DGUV Publikationen",
        "feed_url": "https://publikationen.dguv.de/rss.xml",
        "category": "normen",
        "fallback_url": "https://publikationen.dguv.de/",
        "max_items": 4,
        "priority": 1,
    },
    {
        "name": "BAuA Presse",
        "feed_url": "https://www.baua.de/DE/Service/Presse/rss.xml",
        "category": "normen",
        "fallback_url": "https://www.baua.de/DE/Service/Presse/Presse.html",
        "max_items": 3,
        "priority": 2,
    },
    {
        "name": "VDE News",
        "feed_url": "https://www.vde.com/de/rss-news",
        "category": "normen",
        "fallback_url": "https://www.vde.com/de",
        "max_items": 3,
        "priority": 3,
    },
    {
        "name": "Fluke Blog",
        "feed_url": "https://www.fluke.com/en/learn/blog/rss",
        "category": "geraete",
        "fallback_url": "https://www.fluke.com/en/learn/blog",
        "max_items": 2,
        "priority": 4,
    },
]

KEYWORDS_HIGH = [
    "dguv",
    "trbs",
    "betrsichv",
    "vde",
    "din en 50678",
    "din en 50699",
    "prüfung",
    "prüffrist",
    "sicherheit",
    "elektrische anlagen",
    "betriebsmittel",
]

KEYWORDS_MEDIUM = [
    "software",
    "secutest",
    "izytroniq",
    "firmware",
    "messgerät",
    "gerätetester",
    "kalibrierung",
    "update",
]

PRACTICE_HINTS = [
    "Prüffristen und Prüfumfang sollten immer nachvollziehbar aus Gefährdungsbeurteilung, Einsatzbedingungen und Erfahrung abgeleitet werden.",
    "Bei Normen- oder Softwareänderungen ist entscheidend, ob sich daraus konkrete Änderungen für Prüfabläufe, Dokumentation oder Grenzwerte ergeben.",
    "Herstellerbeiträge sind für Gerätefunktionen hilfreich, sollten aber fachlich von offiziellen Quellen getrennt betrachtet werden.",
]

TITLE_HINTS = [
    ("0701", "Kann für Reparaturprüfung bzw. Normenumfeld tragbarer Geräte relevant sein."),
    ("0702", "Kann für Wiederholungsprüfung bzw. Normenumfeld tragbarer Geräte relevant sein."),
    ("50678", "Betrifft typischerweise das aktuelle Normenumfeld für Prüfungen nach Reparatur."),
    ("50699", "Betrifft typischerweise das aktuelle Normenumfeld für Wiederholungsprüfungen."),
    ("TRBS", "Kann Auswirkungen auf Prüforganisation, befähigte Personen oder Prüftiefe haben."),
    ("DGUV", "Oft direkt relevant für Prüfpraxis und betriebliche Anforderungen."),
    ("VDE", "Kann normativ oder fachlich für Prüfabläufe relevant sein."),
    ("Fluke", "Eher geräte- oder herstellerbezogen; Praxisnutzen prüfen."),
    ("Gossen", "Eher geräte- oder softwarebezogen; Praxisnutzen prüfen."),
    ("IZYTRONIQ", "Meist relevant für Dokumentation, Verwaltung und Prüfsoftware."),
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


def truncate(text: str, max_len: int = 500) -> str:
    text = (text or "").strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def normalize_date(entry) -> str:
    if entry.get("published_parsed"):
        try:
            dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            return dt.date().isoformat()
        except Exception:
            return ""
    return ""


def fetch_page_excerpt(url: str) -> str:
    try:
        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return truncate(strip_html(response.text), 900)
    except Exception as exc:
        return f"Seite konnte nicht geladen werden: {exc}"


def score_item(title: str, summary: str, category: str, source_priority: int) -> tuple[int, str]:
    text = f"{title} {summary}".lower()
    score = 0

    for kw in KEYWORDS_HIGH:
        if kw in text:
            score += 3

    for kw in KEYWORDS_MEDIUM:
        if kw in text:
            score += 1

    if category == "normen":
        score += 2

    score += max(0, 5 - source_priority)

    if score >= 10:
        level = "Hoch"
    elif score >= 6:
        level = "Mittel"
    else:
        level = "Info"

    return score, level


def derive_practical_note(title: str, summary: str, category: str) -> str:
    hay = f"{title} {summary}"

    for needle, note in TITLE_HINTS:
        if needle.lower() in hay.lower():
            return note

    if category == "normen":
        return "Auf mögliche Auswirkungen auf Prüfabläufe, Prüffristen und Dokumentation prüfen."
    if category == "geraete":
        return "Prüfen, ob das Thema für eingesetzte Messgeräte, Software oder Arbeitsabläufe praktisch relevant ist."
    return "Praxisrelevanz im Zusammenhang mit deinem konkreten Prüfbereich prüfen."


def parse_feed(source: dict) -> list[dict]:
    parsed = feedparser.parse(source["feed_url"])
    items = []

    for entry in parsed.entries[: source["max_items"]]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or source["fallback_url"]).strip()
        summary = strip_html(entry.get("summary") or entry.get("description") or "")
        published = normalize_date(entry)

        if not title:
            continue

        page_excerpt = fetch_page_excerpt(link)
        score, level = score_item(title, summary, source["category"], source["priority"])
        practical_note = derive_practical_note(title, summary, source["category"])

        items.append(
            {
                "source": source["name"],
                "category": source["category"],
                "title": title,
                "link": link,
                "summary": truncate(summary, 700),
                "published": published,
                "page_excerpt": truncate(page_excerpt, 700),
                "score": score,
                "level": level,
                "practical_note": practical_note,
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
                    "score": 0,
                    "level": "Info",
                    "practical_note": "Quelle später erneut prüfen.",
                }
            )

    collected.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    return collected[:12]


def entry_line(item: dict) -> str:
    summary = item.get("summary") or item.get("page_excerpt") or "Keine Kurzbeschreibung verfügbar."
    return (
        "<li>"
        f"<b>{safe_text(item['title'])}</b> "
        f"(<i>{safe_text(item['level'])}</i>, {safe_text(item['source'])})"
        "<br>"
        f"{safe_text(summary)}"
        "<br>"
        f"<small>Praxis: {safe_text(item['practical_note'])}</small>"
        "</li>"
    )


def build_section(title: str, items: list[dict], empty_text: str) -> str:
    blocks = [f"<h4>{safe_text(title)}</h4>"]
    if items:
        blocks.append("<ul>")
        for item in items:
            blocks.append(entry_line(item))
        blocks.append("</ul>")
    else:
        blocks.append(f"<p>{safe_text(empty_text)}</p>")
    return "\n".join(blocks)


def build_weekly_html(items: list[dict], generated: datetime) -> str:
    normen = [x for x in items if x["category"] == "normen"]
    geraete = [x for x in items if x["category"] == "geraete"]
    praxis = [x for x in items if x["category"] == "praxis"]

    intro = (
        "Dieses Weekly wurde automatisch und kostenlos aus öffentlichen Quellen erzeugt. "
        "Die Einträge sind nach vermuteter Relevanz für Prüftechniker vorsortiert."
    )

    blocks = []
    blocks.append("<h3>Prüftechniker Weekly</h3>")
    blocks.append(f"<p>{safe_text(intro)} Stand: {generated.strftime('%d.%m.%Y %H:%M UTC')}.</p>")

    blocks.append(
        build_section(
            "Offizielle Quellen / Normen / Regeln",
            normen[:6],
            "Diese Woche keine normenbezogenen Einträge gefunden.",
        )
    )

    blocks.append(
        build_section(
            "Messgeräte / Hersteller",
            geraete[:5],
            "Diese Woche keine gerätebezogenen Einträge gefunden.",
        )
    )

    # Praxisbereich: erst echte Praxis-Einträge, dann allgemeine Hinweise
    blocks.append("<h4>Praxisrelevanz</h4>")
    if praxis:
        blocks.append("<ul>")
        for item in praxis[:4]:
            blocks.append(entry_line(item))
        for hint in PRACTICE_HINTS:
            blocks.append(f"<li>{safe_text(hint)}</li>")
        blocks.append("</ul>")
    else:
        blocks.append("<ul>")
        for hint in PRACTICE_HINTS:
            blocks.append(f"<li>{safe_text(hint)}</li>")
        if items:
            top = items[0]
            blocks.append(
                f"<li>Höchste automatische Relevanz diese Woche: "
                f"<b>{safe_text(top['title'])}</b> "
                f"({safe_text(top['source'])}, Einstufung: {safe_text(top['level'])}).</li>"
            )
        blocks.append("</ul>")

    blocks.append("<h4>Quellen</h4>")
    if items:
        blocks.append("<ul>")
        for item in items:
            blocks.append(
                f'<li><a href="{safe_text(item["link"])}">{safe_text(item["title"])}</a> '
                f'– {safe_text(item["source"])} ({safe_text(item["category"])})</li>'
            )
        blocks.append("</ul>")
    else:
        blocks.append("<p>Keine Quellen verfügbar.</p>")

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
    <description>Kostenlos automatisch erzeugtes Weekly zu VDE, DGUV, TRBS, Prüfpraxis, Messgeräten und Software.</description>
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
    html_output = build_weekly_html(items, generated)
    xml = build_xml(html_output, generated)

    OUTPUT_XML.write_text(xml, encoding="utf-8")
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": generated.isoformat(),
                "status": "ok-free-mode",
                "mode": "free-no-api",
                "items": items,
                "html_preview": html_output,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("[INFO] Weekly V2 erzeugt")
    print("[INFO] weekly-data.json aktualisiert")
    print("[INFO] prueftechniker-weekly.xml aktualisiert")


if __name__ == "__main__":
    main()
