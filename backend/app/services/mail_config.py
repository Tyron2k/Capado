"""Whether a mail configuration is usable, and who the digest would go to.

Pure. No socket is opened here — this answers "is this configuration complete and plausible", which
is a different question from "does the relay accept it", and conflating the two is how a settings
page ends up unable to tell a typo from a firewall.

The point of validating before sending: a half-configured mail path fails at 02:00 in a scheduled
job, where the error goes into a log nobody reads. Saying "no sender address" while the operator is
still looking at the form costs nothing.

Address parsing is deliberately shallow. A full RFC 5322 validator rejects addresses that real
relays accept and accepts things that no relay routes, so the check here is the one that catches
actual mistakes — a missing @, a trailing comma, a space in the middle — and everything else is left
to the relay, which is the only authority that matters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MailConfig:
    """The configured mail path, as stored."""

    enabled: bool = False
    host: str = ""
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""
    from_address: str = ""
    recipients_raw: str = ""


def parse_recipients(raw: str) -> list[str]:
    """Split the stored recipient list.

    Accepts commas, semicolons and newlines, because an operator pasting from an address book gets
    whichever their client used and being strict about the separator would look like the field is
    broken. Empty entries are dropped rather than kept as empty strings, so a trailing comma is not
    an error.
    """
    separated = raw.replace(";", ",").replace("\n", ",")
    return [part.strip() for part in separated.split(",") if part.strip()]


def looks_like_address(value: str) -> bool:
    """Shallow plausibility check — see the module docstring on why it is shallow."""
    if value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if not local or not domain:
        return False
    # A domain with no dot is legal in an intranet ("relay@internal") and is deliberately
    # accepted: this tool is self-hosted, and rejecting internal addresses would be wrong more
    # often than right here.
    return not any(char.isspace() for char in value)


def validation_errors(config: MailConfig) -> list[str]:
    """Everything wrong with the configuration, in the order an operator would fix it.

    Returns an empty list for a disabled configuration regardless of its contents: a half-filled
    form that is switched off is not an error, and complaining about it would train the operator to
    ignore the messages.
    """
    if not config.enabled:
        return []

    errors: list[str] = []
    if not config.host.strip():
        errors.append("Kein SMTP-Server angegeben.")
    if not 1 <= config.port <= 65535:
        errors.append(f"Port {config.port} liegt außerhalb des gültigen Bereichs.")
    if not config.from_address.strip():
        errors.append("Keine Absenderadresse angegeben.")
    elif not looks_like_address(config.from_address.strip()):
        errors.append(
            f"Absenderadresse „{config.from_address}“ ist keine E-Mail-Adresse."
        )

    recipients = parse_recipients(config.recipients_raw)
    if not recipients:
        errors.append("Keine Empfänger angegeben — es würde nichts versendet.")
    else:
        bad = [address for address in recipients if not looks_like_address(address)]
        if bad:
            errors.append("Ungültige Empfängeradressen: " + ", ".join(bad))

    # A username with no password is almost always a half-finished entry rather than an
    # intentional passwordless login, and the relay's rejection would arrive hours later in a
    # scheduled job's log.
    if config.username.strip() and not config.password:
        errors.append("Benutzername ohne Passwort — die Anmeldung würde fehlschlagen.")

    return errors


def is_ready(config: MailConfig) -> bool:
    """Whether the digest could actually be sent with this configuration."""
    return config.enabled and not validation_errors(config)
