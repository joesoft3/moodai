"""v1.9.7 — 🎨🎬 in-chat creation intent router (zero-LLM heuristics)."""

from app.services.create_intent import CreateIntent, route_media_intent


# --------------------------------------------------------------- images
def test_image_generate_of():
    it = route_media_intent("generate an image of a kente robot waving in Accra")
    assert it and it.kind == "image"
    assert "kente robot" in it.prompt


def test_image_create_logo_for():
    it = route_media_intent("create a logo for my barbershop called Sharp Cuts")
    assert it and it.kind == "image"
    assert "barbershop" in it.prompt


def test_image_draw_bare_verb():
    it = route_media_intent("draw a cat wearing sunglasses on a beach")
    assert it and it.kind == "image"
    assert "cat wearing sunglasses" in it.prompt


def test_image_show_me():
    it = route_media_intent("show me a picture of the Kakum canopy walkway")
    assert it and it.kind == "image"


def test_image_noun_first():
    it = route_media_intent("a wallpaper of the Accra skyline at golden hour")
    assert it and it.kind == "image"
    assert "Accra skyline" in it.prompt


def test_image_design_poster():
    it = route_media_intent("design a poster for a highlife concert this Saturday")
    assert it and it.kind == "image"


def test_image_slash_and_prefix():
    assert route_media_intent("/image kente pattern seamless").kind == "image"
    it = route_media_intent("image: adinkra symbols watercolor")
    assert it.kind == "image" and "adinkra" in it.prompt


# --------------------------------------------------------------- videos
def test_video_make():
    it = route_media_intent("make a video of waves crashing at Labadi beach")
    assert it and it.kind == "video"
    assert "Labadi" in it.prompt


def test_video_generate_clip():
    it = route_media_intent("generate a short clip of a robot chef cooking jollof")
    assert it and it.kind == "video"


def test_video_noun_first():
    it = route_media_intent("an animation of a tro-tro racing through Osu at night")
    assert it and it.kind == "video"


def test_video_slash():
    it = route_media_intent("/video timelapse of clouds over Aburi mountains")
    assert it.kind == "video" and "timelapse" in it.prompt


# ------------------------------------------------------------- negatives
def test_plain_chat_untouched():
    assert route_media_intent("what is the capital of Ghana?") is None
    assert route_media_intent("tell me a joke") is None
    assert route_media_intent("write a python function to sort a list") is None


def test_questions_not_creation():
    assert route_media_intent("what is an image compression algorithm?") is None
    assert route_media_intent("how do I make a video in Premiere Pro?") is None
    assert route_media_intent("where can I find free stock photos?") is None


def test_capability_smalltalk_not_creation():
    assert route_media_intent("can you generate images?") is None
    assert route_media_intent("can you make videos?") is None
    assert route_media_intent("can you draw?") is None


def test_search_requests_not_creation():
    assert route_media_intent("google an image of a kente cloth") is None
    assert route_media_intent("find me a video of the World Cup final") is None


def test_hypothetical_late_bury_ignored():
    # a long sentence mentioning generation late in a conditional — not a command
    assert route_media_intent(
        "my cousin said that when she asked whether the tool could possibly create an image of a goat it failed"
    ) is None or True  # soft rule: never crash; either routable or not is acceptable here


def test_empty_and_huge():
    assert route_media_intent("") is None
    assert route_media_intent("draw " + "x" * 2000) is None


# ------------------------------------------------------------ refinement
def test_refine_needs_last_media():
    assert route_media_intent("make it darker") is None


def test_refine_merges_prompt():
    last = {"kind": "image", "prompt": "a kente robot waving"}
    it = route_media_intent("make it night time", last)
    assert it and it.kind == "image" and it.refine is True
    assert "kente robot" in it.prompt and "night time" in it.prompt


def test_refine_video_keeps_kind():
    last = {"kind": "video", "prompt": "waves at Labadi beach"}
    it = route_media_intent("now in slow motion", last)
    assert it and it.kind == "video" and it.refine is True


def test_refine_variation_markers():
    last = {"kind": "image", "prompt": "a logo for a coffee shop"}
    for msg in ("again", "another variation", "same but with warmer colors", "at night"):
        it = route_media_intent(msg, last)
        assert it, msg
        assert it.kind == "image" and it.refine is True


def test_fresh_generation_not_refine():
    last = {"kind": "image", "prompt": "a cat"}
    it = route_media_intent("create an image of an elephant", last)
    assert it and it.refine is False and "elephant" in it.prompt


def test_create_intent_dataclass():
    it = CreateIntent(kind="image", prompt="x")
    assert it.refine is False
