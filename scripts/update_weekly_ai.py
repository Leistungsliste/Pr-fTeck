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

USER_AGENT = "Mozilla/5.0 (compatible; PruefdienstleisterWeeklyBot/4.0)"

# Öffentliche Feeds / RSS-nahe Quellen
SOURCES = [
    {
        "name": "BAuA Presse",
        "feed_url": "https://www.baua.de/de/Presse/Aktuelle-Pressemitteilungen/RSS/BAuA-Presse-RSS-Feed.xml",
        "category": "arbeitssicherheit",
        "fallback_url": "https://www.baua.de/",
        "max_items": 6,
        "priority": 1,
    },
    {
        "name": "BG ETEM Aktuelle Meldungen",
        "feed_url": "https://www.bgetem.de/startseite-der-bg-etem/aktuelle-meldungen/RSS",
        "category": "arbeitssicherheit",
        "fallback_url": "https://www.bgetem.de/",
        "max_items": 5,
        "priority": 2,
    },
    {
        "name": "BG ETEM Pressemeldungen",
        "feed_url": "https://www.bgetem.de/presse-aktuelles/pressemeldungen/aktuelle-pressemeldungen/RSS",
        "category": "arbeitssicherheit",
        "fallback_url": "https://www.bgetem.de/",
        "max_items": 5,
        "priority": 3,
    },
    {
        "name": "CERT@VDE News",
        "feed_url": "https://cert.vde.com/en/service/rss-feeds/",
        "category": "vde_normen",
        "fallback_url": "https://cert.vde.com/en/service/rss-feeds/",
        "max_items": 4,
        "priority": 4,
    },
]

# Statische Referenzen ohne RSS, aber fachlich wichtig
STATIC_REFERENCES = [
    {
        "title": "BAuA – Aktuelles",
        "source": "BAuA",
        "category": "arbeitssicherheit",
        "link": "https://www.baua.de/DE/Angebote/Aktuelles",
        "summary": "Amtliche Arbeitsschutz- und Regelwerksinformationen aus dem BAuA-Umfeld.",
        "published": "",
        "score": 8,
        "level": "Hoch",
        "practical_note": "Regelwerks- und Arbeitsschutzänderungen auf Auswirkungen für Prüforganisation, Dokumentation und Fristen prüfen.",
    },
    {
        "title": "DGUV – RSS-Feeds abonnieren",
        "source": "DGUV",
        "category": "arbeitssicherheit",
        "link": "https://www.dguv.de/de/sonstiges/rss-feed-so-gehts/index.jsp",
        "summary": "Zentrale Einstiegsseite der DGUV für RSS-Feeds und aktuelle DGUV-Informationsangebote.",
        "published": "",
        "score": 8,
        "level": "Hoch",
        "practical_note": "Relevant für Prävention, DGUV-Umfeld und Veröffentlichungen mit betrieblicher Wirkung.",
    },
    {
        "title": "VDE Verlag – Normen / Standards",
        "source": "VDE Verlag",
        "category": "vde_normen",
        "link": "https://www.vde-verlag.de/",
        "summary": "Zentrale Referenz für VDE-Normen und Standards; offene RSS-Abdeckung für Normen selbst ist begrenzt.",
        "published": "",
        "score": 9,
        "level": "Hoch",
        "practical_note": "Für Prüfdienstleister wichtig zur gezielten Beobachtung relevanter Normen wie EN 50678 / EN 50699 und verwandter Standards.",
    },
    {
        "title": "CERT@VDE – RSS Feeds",
        "source": "CERT@VDE",
        "category": "vde_normen",
        "link": "https://cert.vde.com/en/service/rss-feeds/",
        "summary": "VDE-nahe News- und Advisory-Feeds für technische Sicherheits- und Produktthemen.",
        "published": "",
        "score": 7,
        "level": "Mittel",
        "practical_note": "Besonders interessant bei Produktsicherheit, Industrial Security und gerätenahen Sicherheitsthemen.",
    },
]

HIGH_KEYWORDS = [
    "dguv",
    "trbs",
    "betrsichv",
    "baua",
    "vde",
    "din",
    "en 50678",
    "en 50699",
    "prüfung",
    "prüffrist",
    "arbeitsschutz",
    "sicherheit",
    "betriebsmittel",
    "elektrische anlagen",
    "elektrisch",
    "regelwerk",
    "befähigte person",
    "gefahrstoff",
    "prävention",
]

MEDIUM_KEYWORDS = [
    "messgerät",
    "gerätetester",
    "software",
    "firmware",
    "kalibrierung",
    "dokumentation",
    "schutz",
    "rückruf",
    "produkt",
    "seminar",
    "update",
    "advisory",
    "bulletin",
]

PRACTICE_HINTS = [
    "Für Prüfdienstleister sind Änderungen bei Arbeitsschutz, BetrSichV/TRBS, DGUV-Umfeld und Normen besonders relevant, wenn sie Prüforganisation, Prüftiefe, Fristen oder Dokumentation beeinflussen.",
    "Beim Normenumfeld sollte immer geprüft werden, ob sich die Änderung direkt auf Arbeitsanweisungen, Messabläufe oder Protokolle auswirkt.",
    "VDE-/Normenquellen sind fachlich besonders wichtig, auch wenn es dafür nicht immer einen einfachen offenen News-RSS wie bei klassischen Medien gibt.",
    "Hersteller- und Technikbeiträge sind nützlich, sollten aber für einen Prüfdienstleister immer von amtlichen und regelwerksnahen Quellen getrennt bewertet werden.",
]

TITLE_HINTS = [
    ("TRBS", "Kann Auswirkungen auf Prüforganisation, befähigte Personen, Prüftiefe oder Dokumentationspflichten haben."),
    ("DGUV", "Oft direkt relevant für Prävention, betriebliche Anforderungen und Prüfpraxis."),
    ("BAuA", "Amtliche Einordnung aus dem Arbeitsschutz- und Regelwerksumfeld."),
    ("VDE", "Kann normativ oder technisch für Prüfabläufe, Messverfahren oder Dokumentation relevant sein."),
    ("50678", "Betrifft typischerweise Prüfungen nach Reparatur bzw. das zugehörige Normenumfeld."),
    ("50699", "Betrifft typischerweise Wiederholungsprüfungen bzw. das zugehörige Normenumfeld."),
    ("Rückruf", "Kann für Produktsicherheit und Kundenhinweise praktisch relevant sein."),
    ("Advisory", "Auf konkrete Produkt- oder Sicherheitsrelevanz für den Prüfalltag prüfen."),
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


def truncate(text: str, max_len: int = 700) -> str:
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

    for kw in HIGH_KEYWORDS:
        if kw in text:
            score += 3

    for kw in MEDIUM_KEYWORDS:
        if kw in text:
            score += 1

    if category == "arbeitssicherheit":
        score += 3
    elif category == "vde_normen":
        score += 3
    elif category == "messgeraete":
        score += 2

    score += max(0, 5 - source_priority)

    if score >= 11:
        level = "Kritisch"
    elif score >= 8:
        level = "Hoch"
    elif score >= 5:
        level = "Mittel"
    else:
        level = "Info"

    return score, level


def derive_practical_note(title: str, summary: str, category: str) -> str:
    hay = f"{title} {summary}"

    for needle, note in TITLE_HINTS:
        if needle.lower() in hay.lower():
            return note

    if category == "arbeitssicherheit":
        return "Auf Auswirkungen auf Gefährdungsbeurteilung, Prüforganisation, Dokumentation und betriebliche Abläufe prüfen."
    if category == "vde_normen":
        return "Auf Änderungen mit direktem Einfluss auf Prüfabläufe, Messverfahren oder Prüfanweisungen prüfen."
    if category == "messgeraete":
        return "Auf praktische Relevanz für eingesetzte Prüfgeräte, Software oder Kalibrierprozesse prüfen."
    return "Thema fachlich auf Relevanz für Prüfdienstleistungen einordnen."


def is_relevant_item(title: str, summary: str, excerpt: str) -> bool:
    text = f"{title} {summary} {excerpt}".lower()
    score = 0

    for kw in HIGH_KEYWORDS:
        if kw in text:
            score += 2

    for kw in MEDIUM_KEYWORDS:
        if kw in text:
            score += 1

    return score >= 2


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

        if not is_relevant_item(title, summary, page_excerpt):
            continue

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
            print(f"[INFO] {source['name']}: {len(source_items)} relevante Einträge gesammelt")
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

    collected.extend(STATIC_REFERENCES)
    collected.sort(key=lambda x: (x["score"], x["published"]), reverse=True)
    return collected[:14]


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
    arbeit = [x for x in items if x["category"] == "arbeitssicherheit"]
    normen = [x for x in items if x["category"] == "vde_normen"]
    geraete = [x for x in items if x["category"] == "messgeraete"]

    intro = (
        "Dieses Weekly wurde automatisch und kostenlos aus öffentlich erreichbaren Quellen erzeugt. "
        "Es ist auf Arbeitssicherheit, Normenumfeld und Praxisrelevanz für Prüfdienstleister ausgerichtet."
    )

    blocks = []
    blocks.append("<h3>Prüfdienstleister Weekly</h3>")
    blocks.append(f"<p>{safe_text(intro)} Stand: {generated.strftime('%d.%m.%Y %H:%M UTC')}.</p>")

    blocks.append(
        build_section(
            "Arbeitssicherheit / Arbeitsschutz / Regelwerk",
            arbeit[:6],
            "Diese Woche keine relevanten Einträge aus Arbeitssicherheit oder Regelwerksumfeld gefunden.",
        )
    )

    blocks.append(
        build_section(
            "VDE / Normenumfeld / technische Sicherheit",
            normen[:6],
            "Diese Woche keine relevanten Einträge aus dem VDE-/Normenumfeld gefunden.",
        )
    )

    blocks.append(
        build_section(
            "Messgeräte / Prüfsoftware / Produktthemen",
            geraete[:5],
            "Diese Woche keine relevanten geräte- oder softwarebezogenen Einträge gefunden.",
        )
    )

    blocks.append("<h4>Praxisrelevanz für Prüfdienstleister</h4>")
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
    guid = f"pruefdienstleister-weekly-{generated.strftime('%Y-%m-%d-%H%M%S')}"
    title = f"Prüfdienstleister Weekly – {generated.strftime('%d.%m.%Y')}"

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Prüfdienstleister Weekly Update</title>
    <link>{REPO_BASE_URL}/prueftechniker-weekly.xml</link>
    <description>Kostenlos automatisch erzeugtes Weekly zu Arbeitssicherheit, VDE-/Normenumfeld und relevanten Themen für Prüfdienstleister.</description>
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
                "scope": "arbeitssicherheit-vde-pruefdienstleister",
                "items": items,
                "html_preview": html_output,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("[INFO] Prüfdienstleister Weekly erzeugt")
    print("[INFO] weekly-data.json aktualisiert")
    print("[INFO] prueftechniker-weekly.xml aktualisiert")


if __name__ == "__main__":
    main()
