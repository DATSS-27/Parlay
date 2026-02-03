import math

# =========================================================
# CORE MATH
# =========================================================
def poisson(lmbda: float, k: int) -> float:
    """Poisson probability"""
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def expected_goals(team: dict, is_home: bool = True) -> float:
    """
    Expected goals:
    1) League avg (home/away)
    2) Fallback ke last 5 avg
    """
    try:
        return float(
            team["league"]["goals"]["for"]["average"][
                "home" if is_home else "away"
            ]
        )
    except Exception:
        return float(team["last_5"]["goals"]["for"]["average"])


def poisson_probs(home_xg: float, away_xg: float, max_goals: int = 5):
    home = draw = away = 0.0

    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            p = poisson(home_xg, h) * poisson(away_xg, a)
            if h > a:
                home += p
            elif h == a:
                draw += p
            else:
                away += p

    return home, draw, away


# =========================================================
# HELPERS
# =========================================================
def pct(val) -> float:
    if not val:
        return 0.0
    return float(str(val).replace("%", "").strip()) / 100


def adjusted_prob(base: float, home: float, away: float, weight: float) -> float:
    total = home + away
    if total <= 0:
        return base

    ratio = home / total
    return base * (1 + (ratio - 0.5) * weight)


# =========================================================
# POISSON HDP ENGINE (PRIMARY)
# =========================================================
def poisson_hdp_engine(pred_resp: dict) -> dict:
    teams = pred_resp["teams"]
    comp = pred_resp.get("comparison", {})

    home = teams["home"]
    away = teams["away"]

    home_xg = expected_goals(home, True)
    away_xg = expected_goals(away, False)

    p_home, p_draw, p_away = poisson_probs(home_xg, away_xg)

    goals = comp.get("goals", {})
    att = comp.get("att", {})
    defense = comp.get("def", {})

    p_home_adj = (
        adjusted_prob(p_home, pct(goals.get("home")), pct(goals.get("away")), 0.20) +
        adjusted_prob(p_home, pct(att.get("home")), pct(att.get("away")), 0.15) +
        adjusted_prob(p_home, pct(defense.get("home")), pct(defense.get("away")), 0.10)
    ) / 3

    p_away_adj = (
        adjusted_prob(p_away, pct(goals.get("away")), pct(goals.get("home")), 0.20) +
        adjusted_prob(p_away, pct(att.get("away")), pct(att.get("home")), 0.15) +
        adjusted_prob(p_away, pct(defense.get("away")), pct(defense.get("home")), 0.10)
    ) / 3

    p_draw_adj = max(0.0, 1 - (p_home_adj + p_away_adj))
    p_draw_adj = min(p_draw_adj, 0.35)

    # ================= HANDICAP MAPPING =================
    if p_home_adj < 0.45 and p_draw_adj > 0.25:
        hdp_home, hdp_away = "0 (DNB)", "+0.25"
    elif 0.45 <= p_home_adj < 0.55:
        hdp_home, hdp_away = "-0.25", "+0.5"
    elif 0.55 <= p_home_adj < 0.60:
        hdp_home, hdp_away = "-0.5", "+0.75"
    else:
        hdp_home, hdp_away = "-0.75", "+1.0"

    return {
        "model": "poisson",
        "home_prob": round(p_home_adj, 3),
        "draw_prob": round(p_draw_adj, 3),
        "away_prob": round(p_away_adj, 3),
        "hdp_home": hdp_home,
        "hdp_away": hdp_away,
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
    }


# =========================================================
# SIMPLE FALLBACK ENGINE
# =========================================================
def simple_hdp_engine(pred_resp: dict) -> dict:
    comp = pred_resp.get("comparison", {})
    total = comp.get("total", {})

    ph = pct(total.get("home"))
    pa = pct(total.get("away"))

    if abs(ph - pa) < 0.05:
        hdp_home, hdp_away = "0 (DNB)", "+0.25"
    elif ph > pa:
        hdp_home, hdp_away = "-0.25", "+0.5"
    else:
        hdp_home, hdp_away = "+0.5", "-0.25"

    return {
        "model": "simple",
        "home_prob": round(ph, 3),
        "draw_prob": round(max(0.0, 1 - (ph + pa)), 3),
        "away_prob": round(pa, 3),
        "hdp_home": hdp_home,
        "hdp_away": hdp_away,
        "home_xg": 0.0,
        "away_xg": 0.0,
    }


# =========================================================
# HDP CONFIDENCE (FINAL)
# =========================================================
def hdp_confidence(hdp_resp: dict, home_xg: float, away_xg: float) -> int:
    """
    Final HDP Confidence (0–100)
    """

    p_home = hdp_resp.get("home_prob", 0.0)
    p_away = hdp_resp.get("away_prob", 0.0)
    p_draw = hdp_resp.get("draw_prob", 0.0)

    hdp_home = hdp_resp.get("hdp_home", "0")
    hdp_away = hdp_resp.get("hdp_away", "0")

    # Favorit side
    cover_prob = max(p_home, p_away)
    cover_score = cover_prob * 100 * 0.6

    # Expected goal diff
    egd = abs(home_xg - away_xg)
    egd_score = min(egd * 25, 25) * 0.2

    # Draw safety
    draw_score = (1 - p_draw) * 100 * 0.2

    confidence = cover_score + egd_score + draw_score

    # Handicap difficulty penalty
    def hdp_val(h):
        try:
            return abs(float(h.split()[0]))
        except Exception:
            return 0.0

    penalty = max(hdp_val(hdp_home), hdp_val(hdp_away)) * 6
    confidence -= penalty

    return int(round(max(0, min(confidence, 100))))


# =========================================================
# PUBLIC API
# =========================================================
def hdp_suggestion(pred_resp: dict) -> dict:
    try:
        return poisson_hdp_engine(pred_resp)
    except Exception:
        return simple_hdp_engine(pred_resp)
