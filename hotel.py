"""The Grand Meridian Hotel front desk: instructions, tools and demo bookings.

Shared by before.py and after.py, so the agent is identical on both sides of the migration.
Everything is in memory and fictional. Changes last until the process exits.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

INSTRUCTIONS = """\
You are the virtual front-desk assistant for the Grand Meridian Hotel, a 420-room city hotel.
You are speaking with a guest over the phone. This is a demo system running on fictional data.

What you can do:
- Look up a reservation by confirmation code (GM followed by 5 digits, for example GM40912)
  or by the guest's last name.
- Cancel a reservation.
- Change the checkout time of a reservation. Late checkout up to 16:00 is free for suites and
  members. Otherwise a 25 GBP fee applies, which you must state before making the change.

You cannot take new bookings, change room types, take payments, or handle billing disputes.
For those, offer to put the guest through to a colleague at the front desk.

How to behave:
- Be warm, brief and natural. One or two sentences per turn. No lists, no markdown, no emoji.
- Identify the reservation before changing anything. If a last name matches more than one
  booking, ask for the arrival date or first name rather than guessing.
- Before you cancel or change a checkout time, say exactly what you are about to do and get
  an explicit yes.
- Never invent reservations, prices, room numbers or policies. If a lookup finds nothing, say
  so and offer the other way of searching.
"""

# Dates are relative to today, so the bookings stay upcoming however old this file gets.
_today = date.today()


def _day(offset: int) -> str:
    return (_today + timedelta(days=offset)).isoformat()


RESERVATIONS = {
    "GM40912": {"guest_name": "Amara Okafor", "last_name": "Okafor", "room_type": "Deluxe King",
                "check_in": _day(3), "check_out": _day(6), "checkout_time": "11:00",
                "member": True, "status": "confirmed"},
    "GM41055": {"guest_name": "Tom Reid", "last_name": "Reid", "room_type": "Standard Twin",
                "check_in": _day(0), "check_out": _day(1), "checkout_time": "11:00",
                "member": False, "status": "confirmed"},
    "GM41182": {"guest_name": "Priya Reid", "last_name": "Reid", "room_type": "Meridian Suite",
                "check_in": _day(4), "check_out": _day(9), "checkout_time": "12:00",
                "member": True, "status": "confirmed"},
    "GM39877": {"guest_name": "Hans Bergmann", "last_name": "Bergmann", "room_type": "Deluxe Twin",
                "check_in": _day(-7), "check_out": _day(-4), "checkout_time": "11:00",
                "member": False, "status": "checked_out"},
}

LATE_CHECKOUT_FEE_GBP = 25
FREE_LATE_CHECKOUT_UNTIL = "16:00"
LATEST_CHECKOUT = "18:00"


def look_up_reservation(confirmation_code: str = "", last_name: str = "") -> dict:
    if confirmation_code:
        code = confirmation_code.strip().upper()
        matches = [(code, RESERVATIONS[code])] if code in RESERVATIONS else []
    elif last_name:
        matches = [(code, r) for code, r in RESERVATIONS.items()
                   if r["last_name"].lower() == last_name.strip().lower()]
    else:
        return {"error": "Provide either a confirmation code or a last name."}
    return {"found": len(matches),
            "reservations": [{"confirmation_code": code, **r} for code, r in matches]}


def cancel_reservation(confirmation_code: str) -> dict:
    code = confirmation_code.strip().upper()
    reservation = RESERVATIONS.get(code)
    if not reservation:
        return {"error": f"No reservation found for {code}."}
    if reservation["status"] != "confirmed":
        return {"error": f"This reservation is {reservation['status']}, so it can't be cancelled."}
    reservation["status"] = "cancelled"
    free = date.fromisoformat(reservation["check_in"]) > _today
    return {"status": "cancelled", "confirmation_code": code,
            "refund": "full" if free else "first night charged"}


def change_checkout_time(confirmation_code: str, new_checkout_time: str) -> dict:
    code = confirmation_code.strip().upper()
    reservation = RESERVATIONS.get(code)
    if not reservation:
        return {"error": f"No reservation found for {code}."}
    if reservation["status"] != "confirmed":
        return {"error": f"This reservation is {reservation['status']}, so checkout can't change."}
    if new_checkout_time > LATEST_CHECKOUT:
        return {"error": f"The latest checkout we can offer is {LATEST_CHECKOUT}."}
    free = new_checkout_time <= FREE_LATE_CHECKOUT_UNTIL and (
        reservation["member"] or "Suite" in reservation["room_type"])
    previous, reservation["checkout_time"] = reservation["checkout_time"], new_checkout_time
    return {"status": "updated", "confirmation_code": code, "previous_checkout_time": previous,
            "new_checkout_time": new_checkout_time, "fee_gbp": 0 if free else LATE_CHECKOUT_FEE_GBP}


_CODE = {"type": "string", "description": "Confirmation code, for example GM40912."}

TOOLS = [
    {"type": "function", "name": "look_up_reservation",
     "description": "Find a reservation by confirmation code or by the guest's last name.",
     "parameters": {"type": "object", "properties": {
         "confirmation_code": _CODE,
         "last_name": {"type": "string", "description": "Guest's last name."}}}},
    {"type": "function", "name": "cancel_reservation",
     "description": "Cancel a reservation. Only call once the guest has explicitly confirmed.",
     "parameters": {"type": "object", "properties": {"confirmation_code": _CODE},
                    "required": ["confirmation_code"]}},
    {"type": "function", "name": "change_checkout_time",
     "description": "Change the checkout time. State any fee and get agreement first.",
     "parameters": {"type": "object", "properties": {
         "confirmation_code": _CODE,
         "new_checkout_time": {"type": "string", "description": "24-hour HH:MM, for example 14:00."}},
         "required": ["confirmation_code", "new_checkout_time"]}},
]

_HANDLERS = {f.__name__: f for f in (look_up_reservation, cancel_reservation, change_checkout_time)}


def run_tool(name: str, arguments: str) -> str:
    """Run a tool call from the model and return its result as a JSON string."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"Unknown tool {name!r}."})
    try:
        return json.dumps(handler(**json.loads(arguments or "{}")))
    except (TypeError, ValueError) as exc:
        return json.dumps({"error": f"Bad arguments for {name}: {exc}"})
