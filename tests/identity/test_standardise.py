"""Match keys: the same thing typed differently must give the same key, and different things must not."""
from halden.identity.standardise import email_key, first_name_key, fold, phone_key, postcode_key


def test_phone_formats_of_one_number_agree():
    forms = ["+44(0)161 4960054", "0161 496 0054", "(0161) 4960054", "+441614960054", "0044 161 496 0054"]
    assert {phone_key(p, "GB") for p in forms} == {"441614960054"}
    assert phone_key("+49(0)2348 391209", "DE") == phone_key("02348 391209", "DE") == "492348391209"


def test_phone_lost_to_excel_gives_no_key():
    assert phone_key("4.47712E+11", "GB") == ""
    assert phone_key(None, "GB") == "" and phone_key(float("nan"), "GB") == ""


def test_phone_extension_is_dropped():
    assert phone_key("0161 496 0054 x12", "GB") == "441614960054"


def test_email_case_spaces_and_gmail_rules():
    assert email_key(" Anna.Smith@GMAIL.com ") == email_key("annasmith+coffee@googlemail.com") == "annasmith@gmail.com"
    # Dots matter outside gmail: these are two different mailboxes.
    assert email_key("anna.smith@outlook.com") != email_key("annasmith@outlook.com")
    assert email_key("not an email") == ""


def test_name_folding_and_nicknames():
    assert fold("Jürgen Groß") == "juergen gross"
    assert fold("Łukasz") == "lukasz" and fold("Ayşe") == "ayse"
    assert first_name_key("Will")[1] == first_name_key("WILLIAM")[1] == "william"
    assert first_name_key("K.") == ("k", "k", True)
    assert first_name_key("Hans D.")[0] == "hans"


def test_postcode_spacing_and_case():
    assert postcode_key("m1 1aa") == postcode_key("M11AA") == "M11AA"
    assert postcode_key(None) == ""
