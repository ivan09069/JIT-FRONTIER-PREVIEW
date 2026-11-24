#!/usr/bin/env python3
"""JIT FRONTIER v0.1.2 -- read-only cross-domain evidence scout.

Uses public APIs (Crossref & GitHub), optional OpenAlex with user key,
proposes hypotheses (NEVER asserts novelty),
and generates a self-contained local HTML exploration report.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

USER_AGENT = "JITFrontierResearchPrototype/0.1.2 (public metadata only)"


@dataclass(frozen=True)
class Source:
    collection: str
    theme: str
    kind: str
    title: str
    url: str
    summary: str
    year: int | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> Source:
        return cls(**{key: value.get(key) for key in cls.__dataclass_fields__})


def read_json_url(url: str, timeout: float = 15.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as result:
        return json.load(result)


def from_crossref(theme: str, limit: int) -> list[Source]:
    qs = urllib.parse.urlencode({
        "query.bibliographic": theme, "rows": limit, "select": "DOI,title,published"
    })
    data = read_json_url("https://api.crossref.org/works?" + qs)
    items = []
    for x in data.get("message", {}).get("items", []):
        doi = x.get("DOI")
        if not doi:
            continue
        title = (x.get("title") or ["Untitled research work"])[0]
        year = None
        parts = x.get("published", {}).get("date-parts", [])
        if parts and parts[0]:
            year = parts[0][0]
        items.append(Source("Crossref", theme, "research", title,
                            "https://doi.org/" + urllib.parse.quote(doi, safe="/"),
                            "Bibliographic record; content and scientific claims have not been independently reviewed.",
                            year))
    return items


def from_openalex(theme: str, limit: int, api_key: str) -> list[Source]:
    qs = urllib.parse.urlencode({
        "search": theme, "per-page": limit,
        "select": "id,title,doi,publication_year,primary_location",
        "api_key": api_key,
    })
    data = read_json_url("https://api.openalex.org/works?" + qs)
    items = []
    for x in data.get("results", []):
        title = x.get("title") or "Untitled research work"
        link = x.get("doi") or x.get("id")
        if not isinstance(link, str) or not link.startswith("https://"):
            continue
        items.append(Source("OpenAlex", theme, "research", title, link,
                            "Bibliographic record; article content and its claims have not been independently reviewed.",
                            x.get("publication_year")))
    return items


def from_github(theme: str, limit: int) -> list[Source]:
    qs = urllib.parse.urlencode({"q": theme, "per_page": limit})
    data = read_json_url("https://api.github.com/search/repositories?" + qs)
    items = []
    for x in data.get("items", []):
        link = x.get("html_url", "")
        if not link.startswith("https://github.com/"):
            continue
        items.append(Source("GitHub", theme, "implementation", x.get("full_name", "Unnamed repo"),
                            link, (x.get("description") or "No repository description supplied.")[:300],
                            None))
    return items


def canonical(url: str) -> str:
    return url.strip().rstrip("/").lower()


def normalize_sources(sources: list[Source]) -> list[Source]:
    unique: dict[str, Source] = {}
    for source in sources:
        if source.url.startswith("https://"):
            unique.setdefault(canonical(source.url), source)
    return list(unique.values())


def make_candidates(sources: list[Source], a: str, b: str, count: int) -> list[dict[str, Any]]:
    # Cross theme, cross source-type pairings only. This is an idea-generation
    # heuristic, not evidence that an invention is new or technically feasible.
    a_sources = [s for s in sources if s.theme == a]
    b_sources = [s for s in sources if s.theme == b]
    pairings = []
    for left in a_sources:
        for right in b_sources:
            if left.kind == right.kind or left.url == right.url:
                continue
            # Prefer recency only as a tie breaker. Not a novelty score.
            year = max(left.year or 0, right.year or 0)
            pairings.append((year, left, right))
    pairings.sort(key=lambda x: (x[0], x[1].title.lower(), x[2].title.lower()), reverse=True)
    cards = []
    seen: set[str] = set()
    used: set[str] = set()
    for _, left, right in pairings:
        key = hashlib.sha256((left.url + "|" + right.url).encode()).hexdigest()[:12]
        if key in seen:
            continue
        seen.add(key)
        # Rotate evidence so multiple top cards are not all the same pairing.
        if (left.url in used or right.url in used) and len(cards) < min(count, 3):
            continue
        used.add(left.url)
        used.add(right.url)
        cards.append({
            "id": key,
            "title": f"Could {a} improve a problem in {b}?",
            "research_question": (
                f"Investigate whether an approach from '{left.title}' "
                f"could address a limitation or unmet need related to '{right.title}'."
            ),
            "source_ids": [left.url, right.url],
            "evidence": [asdict(left), asdict(right)],
            "status": "HYPOTHESIS — UNVERIFIED",
            "prior_art_check": f'Search for existing integrations of "{a}" with "{b}" and compare against both linked sources.',
            "falsifiable_test": (
                "Specify one measurable outcome, identify an accessible baseline, and run a small A/B prototype. "
                "Reject the idea if it cannot improve on the baseline under the chosen cost or reliability constraint."
            ),
            "confidence": "Low: titles/metadata alone do not establish technical compatibility or novelty.",
        })
        if len(cards) == count:
            break
    return cards


STYLES = """
:root{color-scheme:dark;--bg:#03050c;--panel:#090f20;--line:#24536b;--muted:#a7bfd5;--txt:#eefcff;--a:#00f5ff;--b:#ff2bd6;--c:#9361ff;--d:#c8ff45;--warn:#ffd269}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(ellipse at 89% 5%,rgba(110,35,230,.27),transparent 45%),radial-gradient(ellipse at 8% 37%,rgba(0,245,255,.12),transparent 49%),linear-gradient(155deg,#050710,#01030b 70%);color:var(--txt);font:15px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh}
body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;background-image:linear-gradient(to right,rgba(0,245,255,.075) 1px,transparent 1px),linear-gradient(to bottom,rgba(0,245,255,.075) 1px,transparent 1px);background-size:48px 48px;mask-image:linear-gradient(to bottom,black,transparent 90%)}
body:after{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;opacity:.18;background:repeating-linear-gradient(0deg,transparent 0,transparent 3px,rgba(113,163,192,.13) 4px);mix-blend-mode:screen}
main{max-width:1200px;margin:auto;padding:28px 20px 80px}header{border-bottom:1px solid var(--line);padding:4px 0 30px;margin-bottom:32px;box-shadow:0 21px 45px -43px var(--a)}nav{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:40px}.brand-lockup{display:flex;align-items:center;gap:14px}.jit-signature{font-weight:1000;font-style:italic;letter-spacing:-.10em;font-size:34px;color:#f9ffff;line-height:1;text-shadow:0 0 7px rgba(0,245,255,.95),0 0 31px rgba(0,245,255,.55);padding-right:14px;border-right:5px solid var(--a);transform:skewX(-7deg)}.brand-stack{display:flex;flex-direction:column;line-height:1.12}.brand-stack strong{letter-spacing:.22em;font-size:13px;color:#fff;text-shadow:0 0 11px rgba(255,43,214,.55)}.brand-stack small{font-size:9px;color:var(--muted);letter-spacing:.19em;margin-top:4px}.nav-meta{color:var(--d);font:700 11px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.13em;text-shadow:0 0 14px rgba(200,255,69,.35)}
.hero{position:relative;overflow:hidden;max-width:100%;padding:22px 0 16px}.hero:after{content:"";position:absolute;width:145px;height:145px;border:1px solid rgba(0,245,255,.45);border-radius:50%;right:4%;top:4px;box-shadow:0 0 0 16px rgba(0,245,255,.04),0 0 0 38px rgba(255,43,214,.045),0 0 50px rgba(0,245,255,.18);pointer-events:none}.eyebrow{color:var(--d);font-size:11px;letter-spacing:.22em;font-weight:800;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}h1{font-size:clamp(40px,8vw,86px);line-height:1.03;margin:10px 0 16px;letter-spacing:-.065em;font-weight:900}h1 span{background:linear-gradient(115deg,#fff 0%,var(--a) 42%,var(--b) 100%);color:transparent;-webkit-background-clip:text;background-clip:text;filter:drop-shadow(0 0 13px rgba(0,245,255,.24))}.sub{color:#d0e5ef;font-size:17px;max-width:700px}.meta{color:var(--muted);font-size:12px}.mission{font-weight:850;color:#fff;font-size:17px;letter-spacing:.08em;text-shadow:0 0 18px rgba(255,43,214,.36)}.pill{display:inline-block;border:1px solid rgba(0,245,255,.31);background:rgba(3,25,37,.75);padding:7px 12px;margin:6px 6px 0 0;border-radius:6px;color:#d4f4ff;font:700 12px/1.5 ui-monospace,Consolas,monospace;box-shadow:inset 0 0 15px rgba(0,245,255,.045)}.pill:nth-of-type(even){border-color:rgba(255,43,214,.35)}.pill strong{color:var(--a)}
.section-header{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin:10px 0 17px}.section-header strong{font:800 12px/1.5 ui-monospace,Consolas,monospace;letter-spacing:.16em;color:var(--a);text-shadow:0 0 13px rgba(0,245,255,.45)}.section-header small{font:12px ui-monospace,Consolas,monospace;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),1fr));gap:18px}.card{position:relative;overflow:hidden;background:linear-gradient(147deg,rgba(16,25,50,.98),rgba(4,10,22,.98));border:1px solid rgba(0,245,255,.27);border-top:2px solid var(--a);border-radius:12px;padding:21px 22px;box-shadow:0 8px 40px rgba(0,0,0,.55),0 0 24px rgba(0,245,255,.07);transition:border-color .18s,transform .18s,box-shadow .18s}.card:nth-child(even){border-top-color:var(--b)}.card:hover{border-color:var(--b);transform:translateY(-2px);box-shadow:0 9px 45px rgba(0,0,0,.65),0 0 23px rgba(255,43,214,.18)}.card[hidden]{display:none}h2{font-size:19px;line-height:1.35;margin:7px 0 13px;color:#fff}h3{font-size:11px;letter-spacing:.13em;text-transform:uppercase;color:var(--a);margin:20px 0 7px}a{color:#68f8ff;overflow-wrap:anywhere;text-decoration-thickness:1px;text-underline-offset:3px}.status{color:var(--warn);font-size:11px;font-weight:800;letter-spacing:.07em;font-family:ui-monospace,Consolas,monospace}label{display:block;font-size:12px;letter-spacing:.08em;color:#cfecf7;margin-bottom:8px;font-weight:800}input{width:100%;font:inherit;background:#07182a;border:1px solid rgba(0,245,255,.36);padding:14px 16px;color:var(--txt);border-radius:8px;margin:0 0 24px;outline:none}input:focus{border-color:var(--a);box-shadow:0 0 0 2px rgba(0,245,255,.14),0 0 27px rgba(0,245,255,.15)}.source{font-size:13px;border-left:3px solid var(--b);padding-left:11px;margin-top:9px}.footer{margin-top:40px;color:var(--muted);font-size:12px;border-top:1px solid var(--line);padding-top:20px}.footer b{color:#d4f8ff}.footer .signature{color:var(--a);font-weight:900;letter-spacing:.14em;text-shadow:0 0 14px rgba(0,245,255,.4)}
@media(max-width:640px){main{padding:20px 15px 55px}nav{margin-bottom:26px}.nav-meta{font-size:10px}.jit-signature{font-size:30px}.hero:after{width:64px;height:64px;right:12px;opacity:.55}h1{font-size:clamp(38px,12vw,58px)}.sub{font-size:15px}.card{padding:18px}}
@media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;transition:none!important}}
"""


def render_html(report: dict[str, Any]) -> str:
    esc = lambda s: html.escape(str(s), quote=True)
    cards = []
    for c in report["candidates"]:
        src = "".join(
            f'<div class="source"><b>{esc(s["collection"])} · {esc(s["kind"])}</b> — '
            f'<a href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer">{esc(s["title"])}</a></div>'
            for s in c["evidence"]
        )
        cards.append(
            f'<article class="card" data-search="{esc(c["title"] + " " + c["research_question"] + " " + " ".join(s["title"] for s in c["evidence"]))}">'
            f'<div class="status">{esc(c["status"])}</div><h2>{esc(c["title"])}</h2>'
            f'<p>{esc(c["research_question"])}</p><h3>Linked evidence</h3>{src}'
            f'<h3>Prior-art check</h3><p>{esc(c["prior_art_check"])}</p>'
            f'<h3>Cheapest falsification test</h3><p>{esc(c["falsifiable_test"])}</p>'
            f'<p class="meta">{esc(c["confidence"])}</p></article>'
        )
    errors = " ".join(report["retrieval_errors"]) if report["retrieval_errors"] else "None"
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#070712"><title>JIT FRONTIER | Discovery Engine</title><style>{STYLES}</style></head>
<body><main><header><nav><div class="brand-lockup"><div class="jit-signature" aria-label="JIT">JIT</div><div class="brand-stack"><strong>FRONTIER</strong><small>DISCOVERY ENGINE</small></div></div><div class="nav-meta">JIT://DISCOVERY&nbsp; / &nbsp;v0.1.2</div></nav>
<div class="hero"><div class="eyebrow">RESEARCH // CONNECT // CHALLENGE // PROVE</div><h1>THE NEXT <span>FRONTIER.</span></h1>
<p class="mission">FIND THE GAP. BUILD THE PROOF.</p><p class="sub">A cross-domain discovery system that explores underused connections and turns them into testable opportunities. Every idea carries its evidence and its uncertainty.</p></div>
<span class="pill">DOMAIN A: <strong>{esc(report["theme_a"])}</strong></span><span class="pill">DOMAIN B: <strong>{esc(report["theme_b"])}</strong></span>
<span class="pill">{len(report["sources"])} SOURCES</span><span class="pill">{len(report["candidates"])} HYPOTHESES</span>
<p class="meta">Generated: {esc(report["generated_utc"])} · Demonstration data: {esc(report["demo"])} · Retrieval issues: {esc(errors)}</p></header>
<div class="section-header"><strong>OPPORTUNITY SIGNALS</strong><small>REVIEW REQUIRED // NO NOVELTY CLAIMS</small></div>
<label for="filter">SEARCH HYPOTHESES</label><input id="filter" placeholder="Filter by research area, source, or possibility..." autocomplete="off"><section id="cards" class="grid">{''.join(cards) or '<p>No cross-type candidate connections found. Try broader themes.</p>'}</section>
<div class="footer"><span class="signature">JIT // FRONTIER</span><p><b>Evidence boundary:</b> This report is a discovery aid. Public metadata alone cannot establish technical feasibility, patentability, novelty, market demand, safety, or legal freedom to operate. Confirm source contents and conduct prior-art checks before claiming an opportunity is new.</p></div></main>
<script>document.getElementById('filter').addEventListener('input',e=>{{const q=e.target.value.toLowerCase();document.querySelectorAll('.card').forEach(el=>{{el.hidden=!el.dataset.search.toLowerCase().includes(q)}})}})</script></body></html>'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover cross-domain research hypotheses from public source metadata.")
    parser.add_argument("--a", dest="a", default="biomimetic materials", help="First field")
    parser.add_argument("--b", dest="b", default="urban heat mitigation", help="Second field")
    parser.add_argument("--limit", type=int, default=5, help="Records per field per source (1-20)")
    parser.add_argument("--cards", type=int, default=6, help="Maximum opportunity cards (1-20)")
    parser.add_argument("--out", default="report", help="Report output folder")
    parser.add_argument("--fixture", default=None, help="Use a local fixture JSON, explicitly marked as demo")
    parser.add_argument("--openalex-key-file", default=None, help="Optional path to your OpenAlex API key, stored locally; never included in reports")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 20 or not 1 <= args.cards <= 20:
        parser.error("--limit and --cards must be between 1 and 20")
    errors: list[str] = []
    if args.fixture:
        raw = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
        sources = [Source.from_dict(s) for s in raw["sources"]]
        a, b = raw["theme_a"], raw["theme_b"]
        demo = True
    else:
        a, b = args.a, args.b
        demo = False
        sources = []
        openalex_key = None
        if args.openalex_key_file:
            try:
                openalex_key = Path(args.openalex_key_file).read_text(encoding="utf-8").strip()
                if not openalex_key:
                    raise ValueError("OpenAlex key file was empty")
            except OSError as exc:
                print(f"Cannot read OpenAlex key file: {exc}", file=sys.stderr)
                return 2
        for theme in (a, b):
            loaders = [(from_crossref, (theme, args.limit)), (from_github, (theme, args.limit))]
            if openalex_key:
                loaders.append((from_openalex, (theme, args.limit, openalex_key)))
            for loader, params in loaders:
                try:
                    sources.extend(loader(*params))
                except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    errors.append(f"{getattr(loader, '__name__', 'source_api')} [{theme}]: {str(exc)[:180]}")
        if not sources:
            print("No live evidence fetched; refusing to manufacture research results.", file=sys.stderr)
            for err in errors:
                print("  " + err, file=sys.stderr)
            return 2
    sources = normalize_sources(sources)
    candidates = make_candidates(sources, a, b, args.cards)
    report = {
        "name": "JIT FRONTIER", "version": "0.1.2", "theme_a": a, "theme_b": b,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "demo": demo, "retrieval_errors": errors,
        "sources": [asdict(s) for s in sources], "candidates": candidates,
    }
    folder = Path(args.out)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "opportunities.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (folder / "index.html").write_text(render_html(report), encoding="utf-8")
    print(f"Sources: {len(sources)} | Hypotheses: {len(candidates)} | Demo: {demo}")
    print("JSON:", (folder / "opportunities.json").resolve())
    print("Dashboard:", (folder / "index.html").resolve())
    if errors:
        print("WARNING: Some sources failed to load; see report for details.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
