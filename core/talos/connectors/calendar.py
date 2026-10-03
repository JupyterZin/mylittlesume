"""Conector Google Calendar. Convites com convidados só pelo executor."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol


class CalendarAPI(Protocol):
    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]: ...
    def create_event(self, event: dict[str, Any], *, send_updates: str = "none") -> dict[str, Any]: ...


def free_slots(events: list[dict[str, Any]], start: datetime, end: datetime,
               min_minutes: int = 30) -> list[tuple[datetime, datetime]]:
    busy = sorted(
        (datetime.fromisoformat(e["start"]), datetime.fromisoformat(e["end"])) for e in events
        if e.get("start") and e.get("end") and "T" in e["start"]
    )
    slots, cursor = [], start
    for b_start, b_end in busy:
        if b_start - cursor >= timedelta(minutes=min_minutes):
            slots.append((cursor, b_start))
        cursor = max(cursor, b_end)
    if end - cursor >= timedelta(minutes=min_minutes):
        slots.append((cursor, end))
    return slots


class GoogleCalendar:
    def __init__(self, creds: Any, calendar_id: str = "primary") -> None:
        from googleapiclient.discovery import build

        self.svc = build("calendar", "v3", credentials=creds, cache_discovery=False)
        self.cal = calendar_id

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        res = self.svc.events().list(calendarId=self.cal, timeMin=time_min.isoformat(), timeMax=time_max.isoformat(),
                                     singleEvents=True, orderBy="startTime", maxResults=100).execute()
        out = []
        for e in res.get("items", []):
            out.append({
                "id": e["id"], "summary": e.get("summary", ""), "location": e.get("location", ""),
                "start": e["start"].get("dateTime") or e["start"].get("date"),
                "end": e["end"].get("dateTime") or e["end"].get("date"),
                "attendees": [a.get("email") for a in e.get("attendees", [])],
            })
        return out

    def create_event(self, event: dict[str, Any], *, send_updates: str = "none") -> dict[str, Any]:
        return self.svc.events().insert(calendarId=self.cal, body=event, sendUpdates=send_updates).execute()
