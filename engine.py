# ================= HELPERS =================
def pct(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        return float(val.replace("%", "").strip() or 0)
    return 0.0


def clamp(v: float, lo=0.0, hi=100.0) -> float:
    return max(lo, min(v, hi))

def confidence_percent(diff: float) -> int:
    """
    Convert selisih skor → confidence %
    """
    # diff 0–30 kira-kira
    base = diff * 3.5          # scaling
    conf = 50 + base           # mulai dari 50%

    return int(clamp(conf, 52, 92))
# ================= LEAGUE FORM =================
def league_form_score(form: str) -> float:
    """
    W = 100, D = 50, L = 0
    """
    if not form:
        return 50.0  # netral

    values = [
        100 if c == "W" else
        50 if c == "D" else
        0
        for c in form
    ]
    return sum(values) / len(values)


# ================= FACTOR SCORES =================
def factor_scores(pred_resp: dict, side: str) -> dict:
    team = pred_resp["teams"][side]
    pred = pred_resp["predictions"]
    comp = pred_resp.get("comparison", {})

    goals_for = float(team["last_5"]["goals"]["for"].get("average", 0))
    goals_against = float(team["last_5"]["goals"]["against"].get("average", 0))

    return {
        # === CORE ===
        "percent": clamp(pct(pred["percent"].get(side))),
        "last5_form": clamp(pct(team["last_5"].get("form"))),
        "attack": clamp(pct(team["last_5"].get("att"))),
        "defense": clamp(pct(team["last_5"].get("def"))),

        # === GOALS ===
        "goals_for": clamp(goals_for * 20),          # 2.5 gol ≈ 50
        "goals_against": clamp(100 - goals_against * 20),

        # === SUPPORT ===
        "league_form": league_form_score(
            team.get("league", {}).get("form", "")
        ),
        "h2h": clamp(pct(comp.get("h2h", {}).get(side))),
    }


# ================= WEIGHT CONFIG =================
WEIGHTS = {
    "percent": 0.22,
    "last5_form": 0.14,
    "attack": 0.14,
    "defense": 0.14,
    "goals_for": 0.12,
    "goals_against": 0.12,
    "league_form": 0.07,
    "h2h": 0.05,
}


# ================= FINAL SCORE =================
def final_score(pred_resp: dict, side: str) -> float:
    scores = factor_scores(pred_resp, side)
    total = 0.0

    for k, v in scores.items():
        w = WEIGHTS.get(k, 0)
        total += v * w

    return round(total, 2)


# ================= FINAL DECISION =================
def final_decision(pred_resp: dict) -> dict:
    home_score = final_score(pred_resp, "home")
    away_score = final_score(pred_resp, "away")

    home_name = pred_resp["teams"]["home"]["name"]
    away_name = pred_resp["teams"]["away"]["name"]

    diff = round(abs(home_score - away_score), 2)

    # === PICK LOGIC ===
    if diff < 4:
        pick = "DRAW / DOUBLE CHANCE"
        note = "Kekuatan kedua tim sangat berimbang"
    elif home_score > away_score:
        pick = home_name
        note = f"{home_name} unggul secara statistik"
    else:
        pick = away_name
        note = f"{away_name} unggul secara statistik"

    # === CONFIDENCE ===
    conf_pct = confidence_percent(diff)

    confidence_label = (
        "🟢 Resiko Rendah" if conf_pct >= 80 else
        "🟡 Resiko Sedang" if conf_pct >= 65 else
        "🚨 Resiko Tinggi"
    )

    return {
        "home_score": home_score,
        "away_score": away_score,
        "difference": diff,
        "pick": pick,
        "confidence": confidence,
        "note": note,
    }
