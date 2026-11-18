#!/usr/bin/env python3
"""Merge several RSS/Atom feeds into one RSS 2.0 feed (stdlib only).

Usage: python3 merge_feeds.py [config.json] [output.xml]
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime

UA = "Mozilla/5.0 (compatible; feed-merger/1.0)"
ATOM = "{http://www.w3.org/2005/Atom}"
MEDIA = "{http://search.yahoo.com/mrss/}"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def clean(text, limit=280):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def txt(el, path):
    found = el.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def parse_feed(data):
    root = ET.fromstring(data)
    items = []
    if root.tag == ATOM + "feed":
        for e in root.findall(ATOM + "entry"):
            link = ""
            for l in e.findall(ATOM + "link"):
                if l.get("rel", "alternate") == "alternate":
                    link = l.get("href", "")
                    break
            items.append({
                "title": txt(e, ATOM + "title"),
                "link": link,
                "summary": txt(e, ATOM + "summary") or txt(e, ATOM + "content"),
                "date": parse_date(txt(e, ATOM + "published") or txt(e, ATOM + "updated")),
                "image": "",
            })
    else:
        for i in root.iter("item"):
            image = ""
            enc = i.find("enclosure")
            if enc is not None and (enc.get("type") or "").startswith("image"):
                image = enc.get("url", "")
            for tag in (MEDIA + "content", MEDIA + "thumbnail"):
                m = i.find(tag)
                if not image and m is not None:
                    image = m.get("url", "")
            items.append({
                "title": txt(i, "title"),
                "link": txt(i, "link") or txt(i, "guid"),
                "summary": txt(i, "description"),
                "date": parse_date(txt(i, "pubDate") or txt(i, "{http://purl.org/dc/elements/1.1/}date")),
                "image": image,
            })
    return items


def main():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else "feeds.json"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "public/feed.xml"
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cfg.get("max_age_days", 7))
    per_source = cfg.get("max_per_source", 5)

    merged, seen = [], set()
    for src in cfg["sources"]:
        try:
            items = parse_feed(fetch(src["url"]))
        except Exception as exc:  # one bad feed must not break the rest
            print(f"[WARN] {src['name']}: {exc}", file=sys.stderr)
            continue
        kws = [k.lower() for k in src.get("keywords", [])]
        kept = 0
        for it in sorted(items, key=lambda x: x["date"] or now, reverse=True):
            if kept >= per_source:
                break
            if not it["link"] or it["link"] in seen:
                continue
            if it["date"] and it["date"] < cutoff:
                continue
            if kws and not any(k in (it["title"] + " " + it["summary"]).lower() for k in kws):
                continue
            seen.add(it["link"])
            it["source"] = src["name"]
            it["date"] = it["date"] or now
            merged.append(it)
            kept += 1
        print(f"[OK] {src['name']}: {kept} item", file=sys.stderr)

    merged.sort(key=lambda x: x["date"], reverse=True)
    merged = merged[: cfg.get("max_items", 40)]

    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:media", "http://search.yahoo.com/mrss/")
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = cfg["title"]
    ET.SubElement(ch, "link").text = cfg.get("link", "https://kilavuzteknoloji.com")
    ET.SubElement(ch, "description").text = cfg["description"]
    ET.SubElement(ch, "language").text = "tr"
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(now)
    for it in merged:
        e = ET.SubElement(ch, "item")
        ET.SubElement(e, "title").text = clean(it["title"], 200)
        ET.SubElement(e, "link").text = it["link"]
        ET.SubElement(e, "guid", isPermaLink="true").text = it["link"]
        ET.SubElement(e, "description").text = f"[{it['source']}] {clean(it['summary'])}"
        ET.SubElement(e, "category").text = it["source"]
        ET.SubElement(e, "pubDate").text = format_datetime(it["date"])
        if it["image"]:
            ET.SubElement(e, "media:content", url=it["image"], medium="image")

    import os
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    ET.ElementTree(rss).write(out_path, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(merged)} items to {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
