from dataclasses import dataclass

NEGATIVE_WORDS = [
    "плохо","ужас","ужасно","обман","опоздал","опоздали","испорч","не привез",
    "отстой","отвратительно","кошмар","развод","мошенники","отрава","протухл",
    "тухлый","просроч","жалоба","верните деньги","возврат","холодный","сырой",
    "недовезли","не доставили","разочарован","никогда больше","последний раз",
    "фу","гадость","невкусно","несвежий","брак","бракованный","волос","грязно",
    "игнорируют","не отвечают","роспотребнадзор","претензия","штраф",
]
POSITIVE_WORDS = [
    "круто","отлично","супер","вкусно","вкусный","обожаю","люблю","классно",
    "быстро","свежий","рекомендую","советую","огонь","топ","хорошо","нравится",
    "понравилось","спасибо","благодарю","доволен","довольна","быстрая доставка",
    "вовремя","молодцы","5 звезд","лучший","обожаю","отличный сервис",
]
VIRAL_MARKERS = [
    "всем смотреть","миллион","завирусилось","хайп","тренд","взорвало",
    "репост","поделитесь","50к","100к","миллионный",
]

@dataclass
class RuleResult:
    category:   str    # viral_negative / complaint / positive / neutral / humor
    lane:       str    # pr / smm / none
    confidence: float
    tone:       str    # negative / positive / neutral

def classify_rules(text: str, views: int = 0, likes: int = 0) -> RuleResult:
    t = text.lower()
    neg_hits  = sum(1 for w in NEGATIVE_WORDS if w in t)
    pos_hits  = sum(1 for w in POSITIVE_WORDS if w in t)
    viral     = any(w in t for w in VIRAL_MARKERS) or views > 200_000 or likes > 10_000
    humor_cues = any(w in t for w in ["😂","🤣","прикол","хаха","ахах","смешно","мем"])

    if neg_hits > pos_hits:
        tone      = "negative"
        category  = "viral_negative" if viral else "complaint"
        lane      = "pr"
        confidence = min(0.6 + neg_hits * 0.08, 0.95)
    elif pos_hits > 0:
        tone      = "positive"
        category  = "positive"
        lane      = "smm"
        confidence = min(0.6 + pos_hits * 0.07, 0.90)
    else:
        tone      = "neutral"
        category  = "humor" if humor_cues else "neutral"
        lane      = "smm" if humor_cues else "none"
        confidence = 0.60 if humor_cues else 0.55

    if confidence < 0.6:
        lane = "none"
    return RuleResult(category=category, lane=lane, confidence=confidence, tone=tone)
