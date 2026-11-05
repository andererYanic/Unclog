import pytest

from unclog.ingestion.pii import scrub

FAKE_KEY = "key sk-ant-abcdefghijklmnop1234"  # secret-scan: allow (fake key)


@pytest.mark.parametrize(
    "text,label",
    [
        ("Mail anna.schmidt@acme.de bitte", "[EMAIL]"),
        ("Tel +49 171 2345678", "[PHONE]"),
        ("Tel 030 1234567", "[PHONE]"),
        ("Call (555) 123-4567", "[PHONE]"),
        ("IBAN DE89 3704 0044 0532 0130 00", "[IBAN]"),
        ("Card 4111 1111 1111 1111", "[CARD]"),
        ("api_key=abc123xyz", "[SECRET]"),
        (FAKE_KEY, "[SECRET]"),
    ],
)
def test_redacts(text, label):
    out, n = scrub(text)
    assert label in out and n >= 1


@pytest.mark.parametrize(
    "text",
    [
        "ORD-100234567",
        "Ticket T#40021",
        "case 1002345",
        "2026-10-01 10:00",
        "1234567.50 EUR",
        "v1.2.3",
        "4111 1111 1111 1112",  # fails Luhn
    ],
)
def test_keeps_business_identifiers(text):
    assert scrub(text) == (text, 0)
