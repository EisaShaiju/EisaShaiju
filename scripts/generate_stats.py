#!/usr/bin/env python3
"""
generate_stats.py

Pulls contribution + language data from the GitHub GraphQL API and draws
four SVGs in the same visual language as the portrait. Stdlib only --
nothing here can break in CI because a dependency changed.

Requires env vars:
    GITHUB_TOKEN  -- the Actions-provided token is enough (public data only)
    GH_LOGIN      -- github.repository_owner

Determinism:
    - the contribution window is pinned to whole UTC days (00:00:00 -> 23:59:59),
      not "the last 365 days from right now" -- otherwise the sparkline shifts
      by a fraction of a pixel on every run and you get a nightly no-op commit
    - repositories are filtered to privacy: PUBLIC so the numbers are the same
      regardless of which token (yours or the workflow's) generated them
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from svgkit import ACCENT, DIM, FG, RULE, svg_shell

API_URL = "https://api.github.com/graphql"
RAMP = " .`:-=+*cs#%@"

# Everything these four cards can draw, so the embedded subset is the same in
# each one and the diffs stay small.
CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz :-/,." + RAMP


# ---------------------------------------------------------------- GraphQL --

def gql(token: str, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "profile-stats-script",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read())
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


CONTRIB_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays { date contributionCount }
        }
      }
    }
  }
}
"""

LANG_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, privacy: PUBLIC, isFork: false,
                 ownerAffiliations: [OWNER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def fetch_contributions(token: str, login: str) -> dict:
    today = datetime.now(timezone.utc).replace(hour=23, minute=59, second=59, microsecond=0)
    start = (today - timedelta(days=364)).replace(hour=0, minute=0, second=0)
    data = gql(token, CONTRIB_QUERY, {
        "login": login,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": today.isoformat().replace("+00:00", "Z"),
    })
    return data["user"]["contributionsCollection"]["contributionCalendar"]


def fetch_languages(token: str, login: str) -> dict:
    totals_bytes, totals_repos = {}, {}
    after = None
    while True:
        data = gql(token, LANG_QUERY, {"login": login, "after": after})
        repos = data["user"]["repositories"]
        for repo in repos["nodes"]:
            seen_in_repo = set()
            for edge in repo["languages"]["edges"]:
                name = edge["node"]["name"]
                color = edge["node"]["color"] or "#888888"
                totals_bytes[name] = totals_bytes.get(name, (0, color))
                totals_bytes[name] = (totals_bytes[name][0] + edge["size"], color)
                seen_in_repo.add(name)
            for name in seen_in_repo:
                totals_repos[name] = totals_repos.get(name, 0) + 1
        if not repos["pageInfo"]["hasNextPage"]:
            break
        after = repos["pageInfo"]["endCursor"]
    return totals_bytes, totals_repos


# --------------------------------------------------------------- streaks --

def compute_streaks(calendar: dict):
    days = []
    for week in calendar["weeks"]:
        for d in week["contributionDays"]:
            days.append((d["date"], d["contributionCount"]))
    days.sort()

    longest = longest_start = longest_end = 0
    cur = cur_start = 0
    run_start = None
    for date, count in days:
        if count > 0:
            if run_start is None:
                run_start = date
            cur += 1
            if cur > longest:
                longest = cur
                longest_start, longest_end = run_start, date
        else:
            cur = 0
            run_start = None

    # current streak = trailing run ending today (or yesterday, if today has no contribs yet)
    current = 0
    current_start = None
    for date, count in reversed(days):
        if count > 0:
            current += 1
            current_start = date
        else:
            if current > 0:
                break
    return {
        "current": current,
        "current_start": current_start,
        "current_end": days[-1][0] if current else None,
        "longest": longest,
        "longest_start": longest_start,
        "longest_end": longest_end,
    }


# -------------------------------------------------------------- SVG base --

def card(width: int, height: int, body: str, title: str) -> str:
    return svg_shell(width, height, body, title, chars=CHARS, family="StatsMono")


# ------------------------------------------------------------- hero card --

def build_hero_svg(calendar: dict) -> str:
    total = calendar["totalContributions"]
    weeks = calendar["weeks"]
    weekly = [sum(d["contributionCount"] for d in w["contributionDays"]) for w in weeks]
    weekly = weekly[-26:]  # last ~6 months, sparkline
    w, h = 460, 120
    pad = 16
    plot_w, plot_h = w - 2 * pad, 50
    max_v = max(weekly) or 1
    bar_w = plot_w / len(weekly)

    bars = []
    for i, v in enumerate(weekly):
        bh = (v / max_v) * plot_h
        x = pad + i * bar_w
        y = pad + 40 + (plot_h - bh)
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w * 0.7:.1f}" '
                     f'height="{bh:.1f}" fill="{ACCENT}" opacity="0.85"/>')

    body = f'''
  <text x="{pad}" y="34" font-size="26" fill="{FG}">{total:,}</text>
  <text x="{pad}" y="52" font-size="11" fill="{DIM}">contributions in the last year</text>
  {"".join(bars)}'''
    return card(w, h, body, f"{total} contributions in the last year")


# ------------------------------------------------------------ streak card --

def build_streak_svg(streak: dict) -> str:
    w, h = 460, 120
    body = f'''
  <text x="16" y="34" font-size="26" fill="{FG}">{streak['current']}</text>
  <text x="16" y="52" font-size="11" fill="{DIM}">day current streak</text>
  <text x="16" y="70" font-size="10" fill="{DIM}">{streak['current_start'] or '--'} &#8594; {streak['current_end'] or '--'}</text>

  <text x="240" y="34" font-size="26" fill="{FG}">{streak['longest']}</text>
  <text x="240" y="52" font-size="11" fill="{DIM}">day longest streak</text>
  <text x="240" y="70" font-size="10" fill="{DIM}">{streak['longest_start'] or '--'} &#8594; {streak['longest_end'] or '--'}</text>
  <line x1="220" y1="10" x2="220" y2="80" stroke="{DIM}" stroke-width="0.5"/>'''
    return card(w, h, body, "contribution streaks")


# ------------------------------------------------------------- lang card --

def build_lang_svg(by_bytes: dict, by_repo: dict) -> str:
    w = 460
    top = sorted(by_bytes.items(), key=lambda kv: kv[1][0], reverse=True)[:6]
    total = sum(v[0] for _, v in top) or 1
    row_h = 22
    top_pad = 40
    h = top_pad + row_h * len(top) - 6

    rows = []
    for i, (name, (size, color)) in enumerate(top):
        pct = size / total * 100
        y = top_pad + i * row_h
        bar_w = 200 * (size / top[0][1][0])
        repos = by_repo.get(name, 0)
        rows.append(f'''
  <circle cx="16" cy="{y - 4}" r="4" fill="{color}"/>
  <text x="28" y="{y}" font-size="11" fill="{FG}">{name}</text>
  <rect x="140" y="{y - 9}" width="200" height="8" fill="{RULE}"/>
  <rect x="140" y="{y - 9}" width="{bar_w:.1f}" height="8" fill="{color}"/>
  <text x="350" y="{y}" font-size="10" fill="{DIM}">{pct:.1f}% - {repos} repo{'s' if repos != 1 else ''}</text>''')

    body = f'<text x="16" y="16" font-size="11" fill="{DIM}">top languages, by bytes</text>' + "".join(rows)
    return card(w, h, body, "top languages")


# -------------------------------------------------------------- year map --

def build_year_svg(calendar: dict) -> str:
    weeks = calendar["weeks"]
    cell, gap = 10, 2
    w = 16 + len(weeks) * (cell + gap)
    h = 40 + 7 * (cell + gap)
    counts = [d["contributionCount"] for wk in weeks for d in wk["contributionDays"]]
    max_v = max(counts) if counts else 1

    def ramp_char(v):
        if max_v == 0:
            return RAMP[0]
        idx = int((v / max_v) * (len(RAMP) - 1))
        return RAMP[min(idx, len(RAMP) - 1)]

    cells = []
    for wi, week in enumerate(weeks):
        for di, day in enumerate(week["contributionDays"]):
            x = 16 + wi * (cell + gap)
            y = 32 + di * (cell + gap)
            v = day["contributionCount"]
            opacity = 0.15 if v == 0 else min(1.0, 0.25 + v / max_v * 0.75)
            cells.append(f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" '
                         f'rx="2" fill="{ACCENT}" opacity="{opacity:.2f}"/>')

    body = f'<text x="16" y="16" font-size="11" fill="{DIM}">{sum(counts):,} contributions, one cell per day</text>' + "".join(cells)
    return card(w, h, body, "contributions calendar")


# ------------------------------------------------------------------ main --

def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("GH_LOGIN")
    if not token or not login:
        print("GITHUB_TOKEN and GH_LOGIN must be set", file=sys.stderr)
        sys.exit(1)

    out_dir = Path(__file__).parent.parent
    calendar = fetch_contributions(token, login)
    streak = compute_streaks(calendar)
    by_bytes, by_repo = fetch_languages(token, login)

    (out_dir / "stats.svg").write_text(build_hero_svg(calendar))
    (out_dir / "streak.svg").write_text(build_streak_svg(streak))
    (out_dir / "langs.svg").write_text(build_lang_svg(by_bytes, by_repo))
    (out_dir / "year.svg").write_text(build_year_svg(calendar))
    print("wrote stats.svg, streak.svg, langs.svg, year.svg")


if __name__ == "__main__":
    main()
