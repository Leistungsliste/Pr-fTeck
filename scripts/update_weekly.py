import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import feedparser
import html

REPO_BASE_URL = "https://leistungsliste.github.io/Pr-tleck"
OUTPUT_XML = Path("prueftechniker-weekly.xml")
OUTPUT_JSON = Path("weekly-data.json")

SOURCES = [
    {
        "name": "DGUV Publikationen",
        "url": "https://publikationen.dguv.de/rss.xml",
        "category": "normen",
        "priority": 1,
    },
    {
        "name": "BAuA Presse",
        "url": "https://www.baua.de/DE/Service/Presse/rss.xml",
        "category": "normen",
        "priority": 2,
    },
    {
        "name": "VDE News",
        "url": "https://www.vde.com/de/rss-news",
        "category": "normen",
        "priority": 3,
    },
    {
        "name": "Fluke Blog",
        "url": "https://www.fluke.com/en/learn/blog/rss",
        "category": "geraete",
        "priority": 4,
    },
]

FALLBACK_LINKS = {
    "DGUV Publikationen": "https://publikationen.dguv.de/",
    "BAuA Presse": "https://www.baua.de/DE/Service/Presse/Presse.html",
    "VDE News": "https://www.vde.com/de",
    "Fluke Blog": "https://www.fluke.com/en/learn/blog",
}

STATIC_PRACTICE_NOTES = [
    "Für Prüftechniker sind vor allem Änderungen mit direkter Auswirkung auf Prüffristen, Dokumentation, Normenumstellung und Gerätesoftware relevant.",
    "Herstellerquellen sind hilfreich für Gerätefunktionen und Softwarestände, offizielle Quellen bleiben jedoch maßgeblich für verbindliche Einordnung.",
    "Neue Beiträge sollten immer kurz darauf geprüft werden, ob sie OVV, ortsfeste Anlagen, Maschinenprüfung oder reine Produktwerbung betreffen.",
]

def now_utc():
    return datetime.now(timezone.utc)

def safe_text(value: str) -> str:
    return html.escape((value or "").strip(), quote=True)

def parse_feed(source):
    parsed = feedparser.parse(source["url"])
    items = []

    for entry in parsed.entries[:4]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or FALLBACK_LINKS.get(source["name"], REPO_BASE_URL)).strip()
        summary = (
            entry.get("summary")
            or entry.get("description")
            or entry.get("subtitle")
            or ""
        ).strip()

        published = ""
        if entry.get("published_parsed"):
            published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            published = published_dt.date().isoformat()

        if title:
            items.append({
                "source": source["name"],
                "category": source["category"],
                "title": title,
                "link": link,
                "summary": summary,
                "published": published,
                "priority": source["priority"],
            })

    return items

def collect_items():
    collected = []
    for source in SOURCES:
        try:
            collected.extend(parse_feed(source))
        except Exception as exc:
            collected.append({
                "source": source["name"],
                "category": source["category"],
                "title": f"Quelle konnte nicht geladen werden: {source['name']}",
                "link": FALLBACK_LINKS.get(source["name"], REPO_BASE_URL),
                "summary": f"Automatischer Hinweis: Feed-Laden fehlgeschlagen ({exc}).",
                "published": "",
                "priority": 99,
            })

    collected.sort(key=lambda x: (x["priority"], x["published"]), reverse=False)
    return collected[:10]

def build_html_description(items, generated_dt):
    blocks = []

    normen = [x for x in items if x["category"] == "normen"]
    geraete = [x for x in items if x["category"] == "geraete"]
    praxis = STATIC_PRACTICE_NOTES

    blocks.append("<h3>Prüftechniker Weekly</h3>")
    blocks.append(f"<p>Automatisch erzeugt am {generated_dt.strftime('%d.%m.%Y %H:%M UTC')}.</p>")

    if normen:
        blocks.append("<h4>Normen / Vorschriften / Offizielle Quellen</h4><ul>")
        for item in normen[:5]:
            title = safe_text(item["title"])
            source = safe_text(item["source"])
            link = safe_text(item["link"])
            blocks.append(f'<li><a href="{link}">{title}</a> <br><small>Quelle: {source}</small></li>')
        blocks.append("</ul>")

    if geraete:
        blocks.append("<h4>Messgeräte / Hersteller</h4><ul>")
        for item in geraete[:5]:
            title = safe_text(item["title"])
            source = safe_text(item["source"])
            link = safe_text(item["link"])
            blocks.append(f'<li><a href="{link}">{title}</a> <br><small>Quelle: {source}</small></li>')
        blocks.append("</ul>")

    blocks.append("<h4>Praxisrelevanz</h4><ul>")
    for note in praxis:
        blocks.append(f"<li>{safe_text(note)}</li>")
    blocks.append("</ul>")

    blocks.append('<p>Hinweis: Diese Ausgabe wird automatisch aus Quellenüberschriften erzeugt. Für fachliche Bewertung und Priorisierung sollte zusätzlich manuell geprüft werden.</p>')

    return "\n".join(blocks)

def build_xml(items):
    generated = now_utc()
    pub_date_rfc2822 = format_datetime(generated)
    item_guid = f"prueftechniker-weekly-{generated.strftime('%Y-%m-%d')}"
    item_title = f"Prüftechniker Weekly – {generated.strftime('%d.%m.%Y')}"
    description_html = build_html_description(items, generated)

    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Prüftechniker Weekly Update</title>
    <link>{REPO_BASE_URL}/prueftechniker-weekly.xml</link>
    <description>Automatisch erzeugtes Weekly zu VDE, DGUV, TRBS, Prüfpraxis, Messgeräten und Software.</description>
    <language>de-de</language>
    <lastBuildDate>{pub_date_rfc2822}</lastBuildDate>
    <ttl>10080</ttl>

    <item>
      <title>{safe_text(item_title)}</title>
      <link>{REPO_BASE_URL}/</link>
      <guid>{item_guid}</guid>
      <pubDate>{pub_date_rfc2822}</pubDate>
      <description><![CDATA[
{description_html}
      ]]></description>
    </item>

  </channel>
</rss>
'''
    return xml, generated

def main():
    items = collect_items()
    xml, generated = build_xml(items)

    OUTPUT_XML.write_text(xml, encoding="utf-8")
    OUTPUT_JSON.write_text(
        json.dumps(
            {
                "generated_at": generated.isoformat(),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

if __name__ == "__main__":
    main()
