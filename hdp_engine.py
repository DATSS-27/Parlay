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

def hdp_cover_prob(
    hdp: str,
    egd: float,
    p_win: float,
    p_draw: float
) -> float:
    """
    Estimasi probabilitas cover HDP (Asia)
    """
    try:
        line = float(hdp.split()[0])
    except Exception:
        return p_win

    # FAVORIT
    if line < 0:
        need = abs(line)

        # contoh: -0.5 → harus menang
        if need == 0.5:
            return p_win

        # -0.75 / -1 → butuh margin
        return max(0.0, p_win - max(0, need - egd) * 0.25)

    # UNDERDOG
    else:
        # +0.5 → menang atau seri
        if line == 0.5:
            return p_win + p_draw

        # +0.75 / +1 → masih aman kalah tipis
        return min(
            1.0,
            p_win + p_draw + max(0, line + egd) * 0.25
        )

# =========================================================
# POISSON HDP ENGINE (PRIMARY)
# =========================================================
def poisson_hdp_engine(pred_resp: dict) -> dict:
    teams = pred_resp["teams"]
    comp = pred_resp.get("comparison", {})

    home = teams["home"]
    away = teams["away"]

    # === Expected Goals ===
    home_xg = expected_goals(home, True)
    away_xg = expected_goals(away, False)

    # === Base Poisson ===
    p_home, p_draw, p_away = poisson_probs(home_xg, away_xg)

    # === Adjustments ===
    goals = comp.get("goals", {})
    att = comp.get("att", {})
    defense = comp.get("def", {})

    def adj(base, a, b, w):
        return adjusted_prob(base, pct(a), pct(b), w)

    p_home_adj = (
        adj(p_home, goals.get("home"), goals.get("away"), 0.20) +
        adj(p_home, att.get("home"), att.get("away"), 0.15) +
        adj(p_home, defense.get("home"), defense.get("away"), 0.10)
    ) / 3

    p_away_adj = (
        adj(p_away, goals.get("away"), goals.get("home"), 0.20) +
        adj(p_away, att.get("away"), att.get("home"), 0.15) +
        adj(p_away, defense.get("away"), defense.get("home"), 0.10)
    ) / 3

    # === Draw handling (dynamic, lebih realistis) ===
    p_draw_adj = max(
        0.0,
        1 - (p_home_adj + p_away_adj)
    )

    draw_cap = 0.45 - abs(home_xg - away_xg) * 0.10
    p_draw_adj = min(p_draw_adj, max(0.25, draw_cap))

    # === Normalize (safety) ===
    total = p_home_adj + p_draw_adj + p_away_adj
    if total > 0:
        p_home_adj /= total
        p_draw_adj /= total
        p_away_adj /= total

    # === Tentukan favorit ===
    home_fav = p_home_adj >= p_away_adj
    p_fav = max(p_home_adj, p_away_adj)

    # === Match imbang → jangan maksa HDP ===
    if abs(p_home_adj - p_away_adj) < 0.05:
        hdp_home = "0 (DNB)"
        hdp_away = "0 (DNB)"
    else:
        line = base_hdp_from_prob(p_fav)

        if home_fav:
            hdp_home = f"-{line}" if line > 0 else "0 (DNB)"
            hdp_away = f"+{line + 0.25}"
        else:
            hdp_home = f"+{line + 0.25}"
            hdp_away = f"-{line}"
    egd = home_xg - away_xg

    home_cover = hdp_cover_prob(
        hdp_home, egd, p_home_adj, p_draw_adj
    )
    away_cover = hdp_cover_prob(
        hdp_away, -egd, p_away_adj, p_draw_adj
    )
    
    if home_cover >= away_cover:
        best_side = "HOME"
        best_hdp = hdp_home
        best_cover = home_cover
    else:
        best_side = "AWAY"
        best_hdp = hdp_away
        best_cover = away_cover

    return {
        "model": "poisson_v2",
        "home_prob": round(p_home_adj, 3),
        "draw_prob": round(p_draw_adj, 3),
        "away_prob": round(p_away_adj, 3),
        "hdp_home": hdp_home,
        "hdp_away": hdp_away,
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2),
        "best_hdp_side": best_side,
        "best_hdp": best_hdp,
        "cover_prob": round(best_cover, 3),

    }
def base_hdp_from_prob(p: float) -> float:
    """
    Mapping probability favorit → garis handicap Asia
    """
    if p < 0.44:
        return 0.0
    elif p < 0.50:
        return 0.25
    elif p < 0.56:
        return 0.5
    elif p < 0.62:
        return 0.75
    elif p < 0.68:
        return 1.0
    else:
        return 1.25

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
def hdp_confidence(
    hdp_resp: dict,
    home_xg: float,
    away_xg: float
) -> int:
    """
    FINAL HDP CONFIDENCE (0–100)
    Berdasarkan PROBABILITAS COVER, bukan menang
    """

    p_home = hdp_resp.get("home_prob", 0.0)
    p_away = hdp_resp.get("away_prob", 0.0)
    p_draw = hdp_resp.get("draw_prob", 0.0)

    hdp_home = hdp_resp.get("hdp_home", "0")
    hdp_away = hdp_resp.get("hdp_away", "0")

    # === Expected Goal Difference ===
    egd_home = home_xg - away_xg
    egd_away = -egd_home

    # === COVER PROBABILITY ===
    home_cover = hdp_cover_prob(
        hdp_home, egd_home, p_home, p_draw
    )
    away_cover = hdp_cover_prob(
        hdp_away, egd_away, p_away, p_draw
    )

    # === PILIH SISI TERBAIK ===
    if home_cover >= away_cover:
        cover_prob = home_cover
        chosen_hdp = hdp_home
    else:
        cover_prob = away_cover
        chosen_hdp = hdp_away

    # ================= SCORE BUILD =================
    # 1️⃣ Cover probability (60%)
    score = cover_prob * 100 * 0.6

    # 2️⃣ Goal diff support (20%)
    egd_support = min(abs(egd_home) * 20, 20)
    score += egd_support * 0.2

    # 3️⃣ Draw safety (20%)
    score += (1 - p_draw) * 100 * 0.2

    # 4️⃣ Handicap difficulty penalty
    try:
        line = abs(float(chosen_hdp.split()[0]))
    except Exception:
        line = 0.0

    score -= line * 6

    return {
        "score": int(round(max(0, min(score, 100)))),
        "best_side": "HOME" if home_cover >= away_cover else "AWAY",
        "cover_prob": round(max(home_cover, away_cover), 3)
    }


# =========================================================
# PUBLIC API
# =========================================================
def hdp_suggestion(pred_resp: dict) -> dict:
    try:
        return poisson_hdp_engine(pred_resp)
    except Exception:
        return simple_hdp_engine(pred_resp)

