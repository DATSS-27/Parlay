# ================= HELPERS =================
def pct(val) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val) / 100 if val > 1 else float(val)
    if isinstance(val, str):
        v = float(val.replace("%", "").strip() or 0)
        return v / 100
    return 0.0


def clamp(v: float, lo=0.0, hi=100.0) -> float:
    return max(lo, min(v, hi))

def confidence_percent(diff: float) -> int:
    base = diff * 2.2   # turunkan agresivitas
    conf = 50 + base
    return int(clamp(conf, 50, 85))

def extract_confidence_percent(conf_str) -> int:
    try:
        return int(str(conf_str).split("(")[1].replace("%)", ""))
    except Exception:
        return 50  # netral

def relative_score(a: float, b: float) -> float:
    """
    Skala 0–100 berbasis perbandingan langsung
    """
    if a + b == 0:
        return 50.0
    return 100 * a / (a + b)

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

def build_insight_note(home_scores: dict, away_scores: dict,
                       home_name: str, away_name: str,
                       diff: float) -> str:
    reasons = []

    def better(k, label):
        if home_scores[k] - away_scores[k] >= 8:
            reasons.append(f"{label} {home_name}")
        elif away_scores[k] - home_scores[k] >= 8:
            reasons.append(f"{label} {away_name}")

    better("attack", "serangan lebih tajam oleh")
    better("defense", "pertahanan lebih solid oleh")
    better("last5_form", "performa terkini lebih konsisten oleh")
    better("goals_for", "produktivitas gol lebih baik dari")
    better("league_form", "rekam jejak liga lebih baik milik")

    if diff < 4:
        return "Kekuatan kedua tim sangat berimbang, potensi hasil imbang cukup tinggi"

    if not reasons:
        return "Perbedaan tipis, keunggulan tidak terlalu dominan"

    return " & ".join(reasons[:2])

# ================= FACTOR SCORES =================
def factor_scores(pred_resp: dict, side: str) -> dict:
    team = pred_resp["teams"][side]
    pred = pred_resp["predictions"]
    comp = pred_resp.get("comparison", {})

    goals_for = float(team["last_5"]["goals"]["for"].get("average", 0))
    goals_against = float(team["last_5"]["goals"]["against"].get("average", 0))
    
    att = pct(team["last_5"].get("att"))
    def_ = pct(team["last_5"].get("def"))
    
    opp = "away" if side == "home" else "home"
    opp_team = pred_resp["teams"][opp]
    
    opp_att = pct(opp_team["last_5"].get("att"))
    opp_def = pct(opp_team["last_5"].get("def"))
    
    return {
        # === CORE ===
        "percent": clamp(pct(pred["percent"].get(side))),
        "last5_form": clamp(pct(team["last_5"].get("form"))),
        
        "attack": clamp(relative_score(att, opp_def)),
        "defense": clamp(relative_score(def_, opp_att)),

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
    "percent": 0.09,
    "last5_form": 0.14,
    "attack": 0.12,
    "defense": 0.12,
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
        total += v * WEIGHTS.get(k, 0)

    # 🔧 home bias normalization
    if side == "home":
        total -= 1.8   # tuning: 1.5–2.2

    return round(total, 2)

# ================= FINAL DECISION =================
def final_decision(pred_resp: dict) -> dict:
    home_name = pred_resp["teams"]["home"]["name"]
    away_name = pred_resp["teams"]["away"]["name"]

    # === HITUNG SCORE ===
    home_score = final_score(pred_resp, "home")
    away_score = final_score(pred_resp, "away")

    diff = round(abs(home_score - away_score), 2)

    # === AMBIL DETAIL FACTOR ===
    home_scores = factor_scores(pred_resp, "home")
    away_scores = factor_scores(pred_resp, "away")

    # === PICK LOGIC ===
    if diff < 5:
        pick = "DRAW / DOUBLE CHANCE"
    elif home_score > away_score:
        pick = home_name
    else:
        pick = away_name

    # === CONFIDENCE NUMERIK ===
    conf_pct = confidence_percent(diff)

    confidence_label = (
        "🟢 Resiko Rendah" if conf_pct >= 80 else
        "🟡 Resiko Sedang" if conf_pct >= 65 else
        "🚨 Resiko Tinggi"
    )

    confidence = f"{confidence_label} ({conf_pct}%)"

    # === NOTE / INSIGHT ===
    note = build_insight_note(
        home_scores=home_scores,
        away_scores=away_scores,
        home_name=home_name,
        away_name=away_name,
        diff=diff
    )

    return {
        "home_score": home_score,
        "away_score": away_score,
        "difference": diff,
        "pick": pick,
        "confidence": confidence,
        "note": note,
    }

def sync_confidence(winner_conf: int, hdp_conf: int) -> dict:
    """
    Sinkronisasi Winner Confidence & HDP Confidence
    Tujuan: menentukan PASAR yang paling layak dimainkan
    """
    if winner_conf >= 80 and hdp_conf >= 75:
        return {
            "tag": "🔥 IDEAL HDP",
            "decision": "HDP FAVORIT",
            "note": "Tim unggul kuat dan berpeluang besar menutup handicap"
        }

    if winner_conf >= 80 and hdp_conf < 65:
        return {
            "tag": "⚠️ WIN ONLY",
            "decision": "MENANG SAJA",
            "note": "Tim unggul, namun margin kemenangan beresiko untuk HDP"
        }

    if winner_conf < 70 and hdp_conf >= 75:
        return {
            "tag": "💎 VALUE HDP",
            "decision": "HDP UNDERDOG",
            "note": "Underdog berpotensi cover handicap walau tidak diunggulkan"
        }

    return {
        "tag": "⛔ SKIP",
        "decision": "NO BET",
        "note": "Tidak ada value yang cukup kuat untuk betting"
    }


