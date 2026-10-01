"""Textes affichés (en français) : comptes à rebours, infobulle, ancienneté."""

from __future__ import annotations

from datetime import datetime, timezone

from .usage_client import UsageSnapshot, UsageWindow

_DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def reset_text(window: UsageWindow | None, now: datetime | None = None) -> str:
    if window is None or window.resets_at is None:
        return ""
    now = now or _now()
    delta = (window.resets_at - now).total_seconds()
    if delta <= 0:
        return "reset imminent"
    minutes = int(delta // 60)
    if minutes < 60:
        return f"reset dans {max(minutes, 1)} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"reset dans {hours} h {minutes:02d}"
    local = window.resets_at.astimezone()
    return f"reset {_DAYS[local.weekday()]} {local:%H:%M}"


def reset_clock(window: UsageWindow | None) -> str:
    if window is None or window.resets_at is None:
        return ""
    local = window.resets_at.astimezone()
    return f"{local:%H:%M}"


def ago_text(when: datetime | None, now: datetime | None = None) -> str:
    if when is None:
        return "Jamais mis à jour"
    seconds = int(((now or _now()) - when).total_seconds())
    if seconds < 10:
        return "Mis à jour à l'instant"
    if seconds < 60:
        return f"Mis à jour il y a {seconds} s"
    minutes = seconds // 60
    if minutes < 60:
        return f"Mis à jour il y a {minutes} min"
    return f"Mis à jour à {when.astimezone():%H:%M}"


def plan_label(plan: str | None) -> str:
    if not plan:
        return "Claude"
    names = {"pro": "Pro", "max": "Max", "team": "Team", "enterprise": "Enterprise"}
    return f"Claude · {names.get(plan.lower(), plan.capitalize())}"


def tooltip(snapshot: UsageSnapshot | None, error: str | None = None) -> str:
    # Windows limite l'infobulle du tray à 127 caractères.
    if snapshot is None:
        return ("Claude Usage · " + (error or "chargement..."))[:127]
    parts = []
    s, w = snapshot.session, snapshot.weekly
    if s:
        clock = reset_clock(s)
        parts.append(f"Session 5h : {round(s.utilization)} %" + (f" · reset {clock}" if clock else ""))
    if w:
        parts.append(f"Semaine : {round(w.utilization)} %")
    text = "\n".join(parts) or "Claude Usage"
    if error:
        text += "\n(hors ligne)"
    return text[:127]
