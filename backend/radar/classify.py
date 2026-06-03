from .classifier_rules import classify_rules, RuleResult

CONFIDENCE_THRESHOLD = 0.65
MODEL_EXPENSIVE = "claude-opus-4-8"
MODEL_DRAFT     = "claude-haiku-4-5"   # reply-draft generation (cheap, fast)

def classify(text: str, views: int = 0, likes: int = 0) -> RuleResult:
    return classify_rules(text, views, likes)
