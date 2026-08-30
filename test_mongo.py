import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = "mongodb+srv://vinayak2shukla:iKzsMszruvGUp2Ru@cluster0.omgde.mongodb.net/"

async def test():
    print("Connecting to MongoDB Atlas...")
    try:
        client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=8000)
        await client.admin.command('ping')
        print("✅ MongoDB Atlas connection SUCCESS!")
        dbs = await client.list_database_names()
        print(f"   Databases found: {dbs}")
    except Exception as e:
        print(f"❌ FAILED: {e}")

asyncio.run(test())
