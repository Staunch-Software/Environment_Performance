"""Seed script — creates admin user, vessel AM UMANG, and 6 tanks."""
import asyncio
import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from sqlalchemy import select
from passlib.context import CryptContext

from app.database import AsyncSessionLocal
from app.models.user import User
from app.models.vessel import Vessel
from app.models.vessel_tank import VesselTank

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ADMIN = {
    "name": "Admin User",
    "email": "admin@orbplatform.com",
    "password": "12345",
    "role": "admin",
}

VESSEL = {
    "name": "AM UMANG",
    "imo_number": "9792058",
    "call_sign": "D5RM3",
}

TANKS = [
    {"tank_name": "Bilge Holding Tank", "tank_code": "bilge_holding", "capacity_m3": 21.40},
    {"tank_name": "Bilge Separated Oil Tank", "tank_code": "bilge_separated_oil", "capacity_m3": 26.10},
    {"tank_name": "Sludge Tank", "tank_code": "sludge", "capacity_m3": 6.10},
    {"tank_name": "Fuel Oil Clean Drain Comp", "tank_code": "fo_clean_drain", "capacity_m3": 2.90},
    {"tank_name": "Waste Oil Settling Tank No.1", "tank_code": "wost_1", "capacity_m3": 1.20},
    {"tank_name": "Waste Oil Settling Tank No.2", "tank_code": "wost_2", "capacity_m3": 1.20},
]


async def seed():
    async with AsyncSessionLocal() as db:
        # Create admin user
        result = await db.execute(select(User).where(User.email == ADMIN["email"]))
        admin = result.scalar_one_or_none()
        if not admin:
            admin = User(
                id=uuid.uuid4(),
                name=ADMIN["name"],
                email=ADMIN["email"],
                password_hash=pwd_context.hash(ADMIN["password"]),
                role=ADMIN["role"],
                is_active=True,
            )
            db.add(admin)
            await db.flush()
            print(f"Created admin user: {ADMIN['email']}")
        else:
            print(f"Admin user already exists: {ADMIN['email']}")

        # Create vessel
        result = await db.execute(select(Vessel).where(Vessel.imo_number == VESSEL["imo_number"]))
        vessel = result.scalar_one_or_none()
        if not vessel:
            vessel = Vessel(
                id=uuid.uuid4(),
                name=VESSEL["name"],
                imo_number=VESSEL["imo_number"],
                call_sign=VESSEL["call_sign"],
                created_by=admin.id,
                is_active=True,
            )
            db.add(vessel)
            await db.flush()
            print(f"Created vessel: {VESSEL['name']}")
        else:
            print(f"Vessel already exists: {VESSEL['name']}")

        # Create tanks
        for t in TANKS:
            result = await db.execute(
                select(VesselTank).where(
                    VesselTank.vessel_id == vessel.id,
                    VesselTank.tank_code == t["tank_code"],
                )
            )
            tank = result.scalar_one_or_none()
            if not tank:
                tank = VesselTank(
                    id=uuid.uuid4(),
                    vessel_id=vessel.id,
                    tank_name=t["tank_name"],
                    tank_code=t["tank_code"],
                    capacity_m3=t["capacity_m3"],
                    is_active=True,
                )
                db.add(tank)
                print(f"  Created tank: {t['tank_name']} ({t['capacity_m3']} m³)")
            else:
                print(f"  Tank already exists: {t['tank_name']}")

        await db.commit()
        print("\nSeed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
