from src.services.instagram_profile import format_instagram_display_name


def test_format_display_name_username_only():
    assert format_instagram_display_name(None, "peter_chang") == "@peter_chang"


def test_format_display_name_name_and_username():
    assert format_instagram_display_name("Peter Chang", "peter_chang") == "Peter Chang (@peter_chang)"
