from datetime import datetime
from zoneinfo import ZoneInfo

WITA = ZoneInfo("Asia/Makassar")


def fmt(v: float | None) -> str:
    if v is None:
        return "  -  "
    return f"{v:>6.1f}"


# ================= TECH INSIGHT =================
def build_insight(
    home_scores: dict,
    away_scores: dict,
    home_name: str,
    away_name: str,
) -> list[str]:
    notes = []

    def diff(a, b):
        return round(a - b)

    # === ATTACK ===
    d = diff(home_scores["attack"], away_scores["attack"])
    if abs(d) >= 8:
        winner = home_name if d > 0 else away_name
        notes.append(f"⚔️ Serangan {winner} lebih tajam +{abs(d)}")

    # === DEFENSE ===
    d = diff(home_scores["defense"], away_scores["defense"])
    if abs(d) >= 8:
        winner = home_name if d > 0 else away_name
        notes.append(f"🛡 Pertahanan {winner} lebih solid +{abs(d)}")

    # === LEAGUE FORM ===
    d = diff(home_scores["league_form"], away_scores["league_form"])

    if abs(d) < 5:
        notes.append("⚖️ Performa liga hampir seimbang")
    else:
        winner = home_name if d > 0 else away_name
        notes.append(f"📈 Performa liga {winner} lebih stabil +{abs(d)}")
        
    # === H2H ===
    if home_scores.get("h2h", 0) >= 80:
        notes.append(f"📊 Rekor pertemuan berpihak ke {home_name}")
    elif away_scores.get("h2h", 0) >= 80:
        notes.append(f"📊 Rekor pertemuan berpihak ke {away_name}")

    return notes[:3]

# ================= FORMATTER (TECHNICAL) =================
def telegram_formatter_technical(
    fixture: dict,
    home_scores: dict,
    away_scores: dict,
    home_total: float,
    away_total: float,
) -> str:
    kickoff = datetime.fromisoformat(
        fixture["kickoff"]
    ).astimezone(WITA)

    delta = round(home_total - away_total, 2)

    lines: list[str] = []

    # ===== HEADER =====
    lines.append("*{fixture['league_name']}*")
    lines.append(
        f"*{fixture['home']} vs {fixture['away']}*"
    )
    lines.append(f"*{kickoff.strftime('%H:%M')} WITA\n*")

    # ===== SUMMARY =====
    lines.append("*PERBANDINGAN*")
    lines.append(f"{fixture['home']} ({home_total:.1f}) VS {fixture['away']} ({away_total:.1f})")
    lines.append(f"Selisih : {delta:+.1f}\n")

    # ===== TECH INSIGHT =====
    insights = build_insight(
        home_scores,
        away_scores,
        fixture["home"],
        fixture["away"],
    )
    if insights:
        lines.append("*ANALISA*")
        for i in insights:
            lines.append(f"- {i}")
        lines.append("")

    # ===== TABLE =====
    lines.append("*STATISTIK*")
    lines.append("```")
    lines.append(f"{'FACTOR':<20}{'HOME':>7}{'AWAY':>7}")
    lines.append("-" * 34)

    factors = [
        ("percent", "Peluang Menang"),
        ("last5_form", "5 Laga Terakhir"),
        ("attack", "Kualitas Serangan"),
        ("defense", "Kualitas Pertahanan"),
        ("goals_for", "Rata-rata Gol"),
        ("goals_against", "Kebobolan"),
        ("league_form", "Performa Liga"),
        ("h2h", "Rekor H2H"),
    ]

    for key, label in factors:
        lines.append(
            f"{label:<20}"
            f"{fmt(home_scores.get(key))}"
            f"{fmt(away_scores.get(key))}"
        )

    lines.append("-" * 34)
    lines.append(
        f"{'TOTAL SCORE':<20}"
        f"{fmt(home_total)}"
        f"{fmt(away_total)}"
    )
    lines.append("```")

    # ===== FOOTNOTE =====
    lines.append(
        "Note:\n"
        "*Rumus Sandiri Jo, Supaya kita nda dpa kse salah...*"
    )

    return "\n".join(lines)

