from datetime import datetime
from zoneinfo import ZoneInfo

WITA = ZoneInfo("Asia/Makassar")

# ================= CONFIG =================
FACTOR_LABELS = [
    ("percent", "Percent"),
    ("last5_form", "Last 5 Form"),
    ("attack", "Attack"),
    ("defense", "Defense"),
    ("goals_avg", "Goals Avg"),
    ("concede_avg", "Concede Avg"),
    ("league_form", "League Form"),
    ("h2h", "H2H"),
    ("comparison_total", "Comparison Tot"),
]


def format_score(v: float | None) -> str:
    if v is None:
        return "  -  "
    return f"{v:>6.1f}"


# ================= AUTO INSIGHT =================
def build_insight(home_scores: dict, away_scores: dict) -> list[str]:
    notes = []

    if home_scores["defense"] > away_scores["defense"] + 10:
        notes.append("🛡 Defense HOME lebih solid")

    if home_scores["attack"] > away_scores["attack"] + 10:
        notes.append("⚔️ Serangan HOME lebih tajam")

    if home_scores.get("h2h") == 100:
        notes.append("📊 Rekor H2H sepenuhnya milik HOME")

    if away_scores["attack"] > home_scores["attack"] + 10:
        notes.append("⚠️ AWAY unggul di sektor serangan")

    if abs(home_scores["league_form"] - away_scores["league_form"]) < 5:
        notes.append("⚖️ Performa liga relatif seimbang")

    return notes[:3]  # maksimal 3 insight


# ================= FORMATTER =================
def telegram_formatter(
    fixture: dict,
    decision: dict,
    home_scores: dict,
    away_scores: dict,
    hdp: dict | None = None,
) -> str:
    kickoff = datetime.fromisoformat(fixture["kickoff"]).astimezone(WITA)
    kickoff_str = kickoff.strftime("%H:%M")

    lines: list[str] = []

    # ===== HEADER =====
    lines.append("📊 *ANALISIS & PREDIKSI PERTANDINGAN*\n")
    lines.append(f"🏆 *{fixture['league_name']}*")
    lines.append(f"⚽ *{fixture['home']}* vs *{fixture['away']}*")
    lines.append(f"⏰ Kickoff: {kickoff_str} WITA\n")

    # ===== MAIN PICK =====
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("🎯 *REKOMENDASI UTAMA*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"✅ *PICK*: {decision['pick']}")
    lines.append(f"📈 *CONFIDENCE*: {decision['confidence']}")
    lines.append(f"📝 {decision['note']}\n")

    # ===== HDP SECTION =====
    if hdp:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚖️ *REKOMENDASI HANDICAP (HDP)*")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        model = hdp.get("model", "poisson").upper()

        lines.append(
            f"🏠 *HOME*: {hdp['hdp_home']} "
            f"(Prob: {hdp.get('home_prob', 0):.1%})"
        )
        lines.append(
            f"🚩 *AWAY*: {hdp['hdp_away']} "
            f"(Prob: {hdp.get('away_prob', 0):.1%})"
        )

        if "draw_prob" in hdp:
            lines.append(
                f"🤝 *DRAW PROB*: {hdp['draw_prob']:.1%}"
            )

        lines.append(f"🧮 Model: `{model}`\n")

    # ===== INSIGHT =====
    insights = build_insight(home_scores, away_scores)
    if insights:
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📈 *RINGKASAN ANALISIS*")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        for note in insights:
            lines.append(f"• {note}")
        lines.append("")

    # ===== TABLE =====
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 *PERBANDINGAN DATA*")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("```")
    lines.append(f"{'FAKTOR':<18}{'HOME':>7}{'AWAY':>7}")
    lines.append("-" * 32)

    for key, label in FACTOR_LABELS:
        lines.append(
            f"{label:<18}"
            f"{format_score(home_scores.get(key))}"
            f"{format_score(away_scores.get(key))}"
        )

    lines.append("-" * 32)
    lines.append(
        f"{'TOTAL SCORE':<18}"
        f"{format_score(decision['home_score'])}"
        f"{format_score(decision['away_score'])}"
    )
    lines.append("```")

    # ===== FOOTNOTE =====
    lines.append(
        "ℹ️ Prediksi berbasis agregasi 9 faktor statistik & "
        "model probabilistik Poisson untuk HDP. "
        "Confidence rendah menandakan potensi hasil terbuka."
    )

    return "\n".join(lines)
