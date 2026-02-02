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


# ================= LEAGUE FORM =================
def league_form_score(form: str) -> float:
    if not form:
        return 0.0

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

    goals_for = team["last_5"]["goals"]["for"].get("average", 0)
    goals_against = team["last_5"]["goals"]["against"].get("average", 0)

    return {
        "percent": pct(pred["percent"].get(side)),
        "last5_form": pct(team["last_5"].get("form")),
        "attack": pct(team["last_5"].get("att")),
        "defense": pct(team["last_5"].get("def")),
        "goals_avg": clamp(float(goals_for) * 20),
        "concede_avg": clamp(100 - float(goals_against) * 20),
        "league_form": league_form_score(
            team.get("league", {}).get("form", "")
        ),
        "h2h": pct(comp.get("h2h", {}).get(side)),
        "comparison_total": pct(comp.get("total", {}).get(side)),
    }


# ================= FINAL SCORE =================
WEIGHT = 1 / 9  # 11.11%

def final_score(pred_resp: dict, side: str) -> float:
    scores = factor_scores(pred_resp, side)
    total = sum(v * WEIGHT for v in scores.values())
    return round(total, 2)


# ================= FINAL DECISION =================
def final_decision(pred_resp: dict) -> dict:
    home_score = final_score(pred_resp, "home")
    away_score = final_score(pred_resp, "away")

    diff = round(abs(home_score - away_score), 2)

    if diff < 5:
        pick = "DRAW / DOUBLE CHANCE"
        note = "Kekuatan relatif seimbang"
    elif home_score > away_score:
        pick = pred_resp["teams"]["home"]["name"]
        note = "HOME unggul berdasarkan agregat data"
    else:
        pick = pred_resp["teams"]["away"]["name"]
        note = "AWAY unggul berdasarkan agregat data"

    confidence = (
        "🟢 Resiko Rendah" if diff >= 15 else
        "🟡 Resiko Sedang" if diff >= 8 else
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


