from pyrogram import Client

API_ID = 35549134
API_HASH = "5ebba5b73f0725bc1b95a134d3911d2c"

app = Client("shazam_session", api_id=API_ID, api_hash=API_HASH)

with app:
    print("✅ Session сохта шуд!")