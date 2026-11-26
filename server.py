import sqlite3
import uuid
import os
from datetime import datetime

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse


DATABASE = "restaurant.db"
RESTAURANT_ID = "res-a"
MAX_CAPACITY_PER_SLOT = 30

mcp = FastMCP("RES A Booking Service")

OPENAI_VERIFICATION_TOKEN = os.environ.get(
    "OPENAI_VERIFICATION_TOKEN",
    ""
)


@mcp.custom_route(
    "/.well-known/openai-apps-challenge",
    methods=["GET"],
)
async def openai_domain_verification(request: Request):
    return PlainTextResponse(OPENAI_VERIFICATION_TOKEN)

def get_connection():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database():
    with get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reservations (
                reservation_id TEXT PRIMARY KEY,
                restaurant_id TEXT NOT NULL,
                reservation_date TEXT NOT NULL,
                reservation_time TEXT NOT NULL,
                party_size INTEGER NOT NULL,
                customer_name TEXT NOT NULL,
                customer_email TEXT,
                customer_phone TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


@mcp.tool
def get_restaurant_info() -> dict:
    """Return RES A restaurant information and booking policies."""
    return {
        "restaurant_id": RESTAURANT_ID,
        "name": "RES A",
        "address": "123 Orchard Road, Singapore",
        "cuisine": "Asian Fusion",
        "phone": "+65 6123 4567",
        "opening_hours": {
            "monday_to_sunday": "11:30-22:30"
        },
        "booking_interval_minutes": 30,
        "maximum_party_size": 12,
        "default_dining_duration_minutes": 90
    }


@mcp.tool
def check_availability(
    reservation_date: str,
    reservation_time: str,
    party_size: int
) -> dict:
    """
    Check whether RES A can accept a reservation.

    Date must use YYYY-MM-DD.
    Time must use HH:MM in 24-hour format.
    """

    try:
        datetime.strptime(reservation_date, "%Y-%m-%d")
        requested_time = datetime.strptime(
            reservation_time, "%H:%M"
        ).time()
    except ValueError:
        return {
            "available": False,
            "error": "Use YYYY-MM-DD for the date and HH:MM for the time."
        }

    if party_size < 1 or party_size > 12:
        return {
            "available": False,
            "error": "Party size must be between 1 and 12."
        }

    opening_time = datetime.strptime("11:30", "%H:%M").time()
    closing_time = datetime.strptime("22:30", "%H:%M").time()

    if requested_time < opening_time or requested_time >= closing_time:
        return {
            "available": False,
            "error": "The requested time is outside opening hours."
        }

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(party_size), 0) AS reserved_guests
            FROM reservations
            WHERE restaurant_id = ?
              AND reservation_date = ?
              AND reservation_time = ?
              AND status = 'confirmed'
            """,
            (
                RESTAURANT_ID,
                reservation_date,
                reservation_time
            ),
        ).fetchone()

    reserved_guests = row["reserved_guests"]
    remaining_capacity = MAX_CAPACITY_PER_SLOT - reserved_guests
    available = remaining_capacity >= party_size

    return {
        "restaurant_id": RESTAURANT_ID,
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "party_size": party_size,
        "available": available,
        "remaining_capacity": remaining_capacity
    }


@mcp.tool
def create_reservation(
    reservation_date: str,
    reservation_time: str,
    party_size: int,
    customer_name: str,
    customer_email: str = "",
    customer_phone: str = ""
) -> dict:
    """
    Create a confirmed reservation after the customer approves it.
    """

    availability = check_availability(
        reservation_date=reservation_date,
        reservation_time=reservation_time,
        party_size=party_size
    )

    if not availability.get("available"):
        return {
            "status": "rejected",
            "reason": availability.get(
                "error",
                "The requested slot is unavailable."
            )
        }

    if not customer_name.strip():
        return {
            "status": "rejected",
            "reason": "Customer name is required."
        }

    reservation_id = f"RESA-{uuid.uuid4().hex[:8].upper()}"

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO reservations (
                reservation_id,
                restaurant_id,
                reservation_date,
                reservation_time,
                party_size,
                customer_name,
                customer_email,
                customer_phone,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reservation_id,
                RESTAURANT_ID,
                reservation_date,
                reservation_time,
                party_size,
                customer_name.strip(),
                customer_email.strip(),
                customer_phone.strip(),
                "confirmed",
                datetime.now().isoformat()
            ),
        )

    return {
        "status": "confirmed",
        "reservation_id": reservation_id,
        "restaurant": "RES A",
        "reservation_date": reservation_date,
        "reservation_time": reservation_time,
        "party_size": party_size,
        "customer_name": customer_name.strip()
    }


@mcp.tool
def get_reservation(reservation_id: str) -> dict:
    """Retrieve a reservation using its confirmation ID."""

    with get_connection() as connection:
        row = connection.execute(
            """
            SELECT *
            FROM reservations
            WHERE reservation_id = ?
            """,
            (reservation_id,),
        ).fetchone()

    if row is None:
        return {
            "found": False,
            "reservation_id": reservation_id
        }

    return {
        "found": True,
        **dict(row)
    }


@mcp.tool
def modify_reservation(
    reservation_id: str,
    new_date: str,
    new_time: str,
    new_party_size: int
) -> dict:
    """Change the date, time or party size of a reservation."""

    existing = get_reservation(reservation_id)

    if not existing.get("found"):
        return {
            "status": "rejected",
            "reason": "Reservation not found."
        }

    if existing["status"] != "confirmed":
        return {
            "status": "rejected",
            "reason": "Only confirmed reservations can be modified."
        }

    availability = check_availability(
        reservation_date=new_date,
        reservation_time=new_time,
        party_size=new_party_size
    )

    if not availability.get("available"):
        return {
            "status": "rejected",
            "reason": availability.get(
                "error",
                "The new slot is unavailable."
            )
        }

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE reservations
            SET reservation_date = ?,
                reservation_time = ?,
                party_size = ?
            WHERE reservation_id = ?
            """,
            (
                new_date,
                new_time,
                new_party_size,
                reservation_id
            ),
        )

    return {
        "status": "modified",
        "reservation_id": reservation_id,
        "reservation_date": new_date,
        "reservation_time": new_time,
        "party_size": new_party_size
    }


@mcp.tool
def cancel_reservation(reservation_id: str) -> dict:
    """Cancel an existing confirmed reservation."""

    existing = get_reservation(reservation_id)

    if not existing.get("found"):
        return {
            "status": "rejected",
            "reason": "Reservation not found."
        }

    with get_connection() as connection:
        connection.execute(
            """
            UPDATE reservations
            SET status = 'cancelled'
            WHERE reservation_id = ?
            """,
            (reservation_id,),
        )

    return {
        "status": "cancelled",
        "reservation_id": reservation_id
    }


if __name__ == "__main__":
    initialize_database()
    port = int(os.environ.get("PORT", "8000"))

    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=port
    )