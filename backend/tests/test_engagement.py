import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from radar.drafts import _system_prompt, _opportunity_prompts

# Words that signal covert astroturfing — must NOT appear in any prompt.
COVERT = ["перехват", "перехватывать", "выдавать себя", "маскир", "притвор"]


def test_system_prompt_competitor_is_transparent():
    p = _system_prompt("competitor", "Tanuki", [])
    low = p.lower()
    assert "официальн" in low                     # reply is openly from the brand
    assert not any(w in low for w in COVERT)


def test_system_prompt_niche_is_transparent():
    p = _system_prompt("niche", "Tanuki", [])
    low = p.lower()
    assert "официальн" in low
    assert not any(w in low for w in COVERT)


def test_opportunity_prompts_are_transparent():
    system, user = _opportunity_prompts(
        comment_text="где лучше заказать суши?",
        source="competitor", competitor="Якитория", brand_name="Tanuki",
    )
    blob = (system + " " + user).lower()
    assert "официальн" in blob
    assert not any(w in blob for w in COVERT)
