import math


# =========================================================
# CORE MATH
# =========================================================
def poisson(lmbda: float, k: int) -> float:
    """Poisson probability"""
    return (math.exp(-lmbda) * (lmbda ** k)) / math.factorial(k)


def expected_goals(team: dict, is_home: bool = True) -> float:
    """
    Ambil expected goals:
    1️⃣ League avg (home/away)
    2️⃣ Fallback ke last 5 avg
    """
    try:
        return float(
            team["league"]["goals"]["for"]["average"][
                "home" if is_home else "away"
            ]
        )
    except Exception:
        return float(team["last_5"]["goals"]["for"]["average"])


def poisson_probs(
    home_xg: float,
    away_xg: float,
    max_goals: int = 5
) -> tuple[float, float, float]:
    """
    Hitung probabilitas HOME / DRAW / AWAY
    berdasarkan distribusi Poisson
    """
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
def pct(val: str | None) -> float:
    """Convert '65%' -> 0.65"""
    if not val:
        return 0.0
    return float(val.replace("%", "").strip()) / 100


def adjusted_prob(
    base: float,
    comp_home: float,
    comp_away: float,
    weight: float
) -> float:
    """
    Adjust base probability menggunakan comparison ratio
    """
    total = comp_home + comp_away
    if total <= 0:
        return base

    ratio = comp_home / total
    adj = 1 + (ratio - 0.5) * weight
    return base * adj


# =========================================================
# PRIMARY ENGINE (POISSON)
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
        adjusted_prob(
            p_home,
            pct(goals.get("home")),
            pct(goals.get("away")),
            0.20,
        )
        + adjusted_prob(
            p_home,
            pct(att.get("home")),
            pct(att.get("away")),
            0.15,
        )
        + adjusted_prob(
            p_home,
            pct(defense.get("home")),
            pct(defense.get("away")),
            0.10,
        )
    ) / 3

    p_away_adj = (
        adjusted_prob(
            p_away,
            pct(goals.get("away")),
            pct(goals.get("home")),
            0.20,
        )
        + adjusted_prob(
            p_away,
            pct(att.get("away")),
            pct(att.get("home")),
            0.15,
        )
        + adjusted_prob(
            p_away,
            pct(defense.get("away")),
            pct(defense.get("home")),
            0.10,
        )
    ) / 3

    p_draw_adj = max(0.0, 1 - (p_home_adj + p_away_adj))
    p_draw_adj = min(p_draw_adj, 0.35)

    if p_home_adj < 0.45 and p_draw_adj > 0.25:
        hdp_home, hdp_away = "0 (DNB)", "+0.25"
    elif 0.45 <= p_home_adj < 0.55:
        hdp_home, hdp_away = "-0.25", "+0.5"
    elif p_home_adj >= 0.60:
        hdp_home, hdp_away = "-0.75", "+1.0"
    else:
        hdp_home, hdp_away = "-0.5", "+0.75"

    return {
        "model": "poisson",
        "home_prob": round(p_home_adj, 3),
        "draw_prob": round(p_draw_adj, 3),
        "away_prob": round(p_away_adj, 3),
        "hdp_home": hdp_home,
        "hdp_away": hdp_away,
    }



# =========================================================
# FALLBACK ENGINE (SIMPLE & SAFE)
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
    }


# =========================================================
# PUBLIC API (FINAL)
# =========================================================
def hdp_suggestion(pred_resp: dict) -> dict:
    """
    FINAL API:
    - Pakai Poisson engine
    - Auto fallback jika error
    """
    try:
        return poisson_hdp_engine(pred_resp)
    except Exception:
        return simple_hdp_engine(pred_resp)

