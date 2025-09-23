import os
import sys
import time
import json
import random
import docker
import requests

WEBHOOK = os.environ.get("WEBHOOK")
if not WEBHOOK:
    print("Error: WEBHOOK environment variable is not set.", file=sys.stderr)
    sys.exit(1)

# load known SteamID → player name map from env
PLAYER_MAP = {}
raw_map = os.environ.get("PLAYER_MAP")
if raw_map:
    try:
        PLAYER_MAP = json.loads(raw_map)
    except json.JSONDecodeError as e:
        print(f"Error: PLAYER_MAP env var is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)

death_messages = [
    "☠️ $PLAYER_NAME was slain.",
    "☠️ $PLAYER_NAME met their doom.",
    "☠️ $PLAYER_NAME fell in glorious battle.",
    "☠️ $PLAYER_NAME drank one too many meads and toppled off a cliff.",
    "☠️ $PLAYER_NAME has joined the great mead hall in the sky.",
    "☠️ $PLAYER_NAME was slain by the cruel hands of fate.",
    "☠️ $PLAYER_NAME fell face-first into the mead hall of the gods.",
    "☠️ $PLAYER_NAME was outwitted by a boar. Truly tragic.",
    "☠️ $PLAYER_NAME went exploring and discovered the afterlife.",
    "☠️ $PLAYER_NAME took one too many arrows to the knee.",
    "☠️ $PLAYER_NAME misread the map and found death instead.",
    "☠️ $PLAYER_NAME took a nap… permanently.",
    "☠️ $PLAYER_NAME rolled a natural 1 on their life check.",
    "☠️ $PLAYER_NAME attempted a diplomacy check… the boar did not negotiate.",
    "☠️ $PLAYER_NAME attempted stealth… and loudly announced their own death.",
    "☠️ $PLAYER_NAME failed their initiative roll… too slow for a second chance.",
    "☠️ $PLAYER_NAME was at the Compton swap meet but the homies never showed up.",
    "☠️ $PLAYER_NAME was waiting for the homies but they went to the wrong swap meet.",
    "☠️ $PLAYER_NAME was waiting on the homies but they got lost on the way (using Apple maps).",
]

def random_death_message(player_name: str) -> str:
    return random.choice(death_messages).replace("$PLAYER_NAME", player_name)

def send_webhook(message: str):
    try:
        requests.post(
            WEBHOOK,
            headers={"Content-Type": "application/json"},
            data=json.dumps({"content": message}),
            timeout=5,
        )
    except Exception as e:
        print(f"Webhook error: {e}", file=sys.stderr)

def main():
    client = docker.from_env()
    try:
        container = client.containers.get("valheim")
    except docker.errors.NotFound:
        print("Error: 'valheim' container not found.", file=sys.stderr)
        sys.exit(1)

    players = dict(PLAYER_MAP)  # pre-fill with known mappings
    pending = []
    welcome_count = 0

    time.sleep(5)

    buffer = b""
    for chunk in container.logs(stream=True, follow=True, tail=0):
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.decode("utf-8", errors="ignore").strip()

            # --- Got connection ---
            if "Got connection SteamID" in line:
                steamid = line.split()[-1]

                if steamid in players:
                    # Already known → increment welcome immediately
                    welcome_count += 1
                else:
                    # Unknown → wait for ZDOID mapping
                    pending.append(steamid)

            # --- Got character ZDOID from ---
            elif "Got character ZDOID from" in line:
                try:
                    player_name = line.split("Got character ZDOID from ")[1].split(" : ")[0]
                    zdoid = line.split(":")[-1].strip()
                except Exception:
                    continue

                if zdoid == "0":
                    continue

                if pending:
                    steamid = pending.pop(0)
                    players[steamid] = player_name

                if welcome_count > 0:
                    welcome_count -= 1
                    send_webhook(f"✅ {player_name} has arrived!")
                else:
                    msg = random_death_message(player_name)
                    send_webhook(msg)

            # --- Closing socket ---
            elif "Closing socket" in line:
                steamid = line.split()[-1]
                player_name = players.get(steamid, "Unknown Player")
                send_webhook(f"❌ {player_name} has dropped.")

if __name__ == "__main__":
    main()

