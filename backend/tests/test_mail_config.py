"""Tests for :mod:`app.services.mail_config`.

Validation exists so a half-configured mail path fails while the operator is still looking at the
form, instead of at 02:00 inside a scheduled job where the error goes into a log nobody reads. The
tests therefore pin what counts as an error and — more importantly — what deliberately does not,
because a validator that complains about a switched-off form trains people to ignore it.

No database, no sockets. All addresses are fictional.
"""

from __future__ import annotations

from app.services.mail_config import (
    MailConfig,
    is_ready,
    looks_like_address,
    parse_recipients,
    validation_errors,
)

GOOD = MailConfig(
    enabled=True,
    host="relay.intern",
    port=587,
    from_address="capado@example.invalid",
    recipients_raw="planung@example.invalid",
)


class TestParseRecipients:
    def test_a_single_address(self):
        assert parse_recipients("a@example.invalid") == ["a@example.invalid"]

    def test_commas_semicolons_and_newlines_all_separate(self):
        """An operator pasting from an address book gets whichever separator their client
        used, and being strict would look like the field is broken."""
        raw = "a@example.invalid; b@example.invalid,\nc@example.invalid"
        assert parse_recipients(raw) == [
            "a@example.invalid",
            "b@example.invalid",
            "c@example.invalid",
        ]

    def test_a_trailing_separator_is_not_an_error(self):
        assert parse_recipients("a@example.invalid,") == ["a@example.invalid"]

    def test_whitespace_is_stripped(self):
        assert parse_recipients("  a@example.invalid  ") == ["a@example.invalid"]

    def test_an_empty_string_yields_nothing(self):
        assert parse_recipients("") == []
        assert parse_recipients("  ,  ; \n ") == []


class TestLooksLikeAddress:
    def test_a_plain_address_passes(self):
        assert looks_like_address("a@example.invalid") is True

    def test_an_intranet_address_without_a_dot_passes(self):
        """Legal on an intranet, and this tool is self-hosted — rejecting it would be wrong
        more often than right here."""
        assert looks_like_address("relay@internal") is True

    def test_a_missing_at_fails(self):
        assert looks_like_address("example.invalid") is False

    def test_two_ats_fail(self):
        assert looks_like_address("a@b@example.invalid") is False

    def test_an_empty_local_or_domain_fails(self):
        assert looks_like_address("@example.invalid") is False
        assert looks_like_address("a@") is False

    def test_an_embedded_space_fails(self):
        assert looks_like_address("a b@example.invalid") is False


class TestValidationErrors:
    def test_a_complete_configuration_has_no_errors(self):
        assert validation_errors(GOOD) == []

    def test_a_disabled_configuration_is_never_an_error(self):
        """A half-filled form that is switched off is not a problem, and complaining about it
        would train the operator to ignore the messages."""
        half_filled = MailConfig(
            enabled=False, host="", from_address="", recipients_raw=""
        )
        assert validation_errors(half_filled) == []

    def test_a_missing_host_is_reported(self):
        errors = validation_errors(MailConfig(**{**GOOD.__dict__, "host": "  "}))
        assert any("SMTP-Server" in error for error in errors)

    def test_a_missing_sender_is_reported(self):
        errors = validation_errors(MailConfig(**{**GOOD.__dict__, "from_address": ""}))
        assert any("Absenderadresse" in error for error in errors)

    def test_a_malformed_sender_is_reported_differently_from_a_missing_one(self):
        """Two different mistakes; one message for both would send the operator looking for
        an empty field that is not empty."""
        errors = validation_errors(
            MailConfig(**{**GOOD.__dict__, "from_address": "kein-at"})
        )
        assert any("keine E-Mail-Adresse" in error for error in errors)

    def test_no_recipients_is_reported_as_nothing_would_be_sent(self):
        """The failure that would otherwise look like success: everything configured, mail
        enabled, and no mail ever arrives."""
        errors = validation_errors(
            MailConfig(**{**GOOD.__dict__, "recipients_raw": ""})
        )
        assert any("nichts versendet" in error for error in errors)

    def test_a_bad_recipient_is_named(self):
        errors = validation_errors(
            MailConfig(
                **{
                    **GOOD.__dict__,
                    "recipients_raw": "gut@example.invalid, schlecht",
                }
            )
        )
        assert any("schlecht" in error for error in errors)

    def test_a_username_without_a_password_is_reported(self):
        """Almost always a half-finished entry, and the relay's rejection would arrive hours
        later in a scheduled job's log."""
        errors = validation_errors(
            MailConfig(**{**GOOD.__dict__, "username": "capado"})
        )
        assert any("ohne Passwort" in error for error in errors)

    def test_a_password_without_a_username_is_not_reported(self):
        """Some relays authenticate by IP and ignore credentials; a stray password is not
        evidence of a mistake."""
        errors = validation_errors(MailConfig(**{**GOOD.__dict__, "password": "x"}))
        assert errors == []

    def test_a_port_out_of_range_is_reported(self):
        errors = validation_errors(MailConfig(**{**GOOD.__dict__, "port": 0}))
        assert any("Port" in error for error in errors)


class TestIsReady:
    def test_a_complete_enabled_configuration_is_ready(self):
        assert is_ready(GOOD) is True

    def test_a_disabled_configuration_is_not_ready_even_when_complete(self):
        """Disabled means disabled. is_ready answering yes for a switched-off configuration
        would make the switch decorative."""
        assert is_ready(MailConfig(**{**GOOD.__dict__, "enabled": False})) is False

    def test_an_incomplete_configuration_is_not_ready(self):
        assert is_ready(MailConfig(**{**GOOD.__dict__, "host": ""})) is False
