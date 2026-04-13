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

# --- Session end leaderboard messages by death count tier ---
SESSION_MESSAGES_NONE = [
    "Zero deaths across the board. Did anyone actually fight anything or was this a fishing trip?",
    "Not a single death? Odin didn't even bother watching this one.",
    "A flawless session. Cowardly, but flawless.",
    "Nobody died. Somewhere a troll is crying because nobody came to visit.",
]

SESSION_MESSAGES_LOW = [  # 1-2 deaths
    "{player} topped the charts with just {deaths} death{s}. Barely a warmup.",
    "With only {deaths} death{s}, {player} \"wins\" the death race. Participation trophy energy.",
    "{player} died {deaths} time{s}. Even the necks thought that was weak.",
    "A modest {deaths} death{s} for {player}. The Valkyries didn't even get out of bed for this.",
]

SESSION_MESSAGES_MED = [  # 3-5 deaths
    "{player} clocked {deaths} deaths. The Valkyries are starting to learn their name.",
    "Congrats to {player} for {deaths} deaths. The corpse run MVP of the evening.",
    "{player} died {deaths} times. Hel put in a revolving door just for them.",
    "{player} with {deaths} deaths! Their grave markers are becoming a tourist attraction.",
    "{player} racked up {deaths} deaths. At this point their tombstone has a tombstone.",
]

SESSION_MESSAGES_HIGH = [  # 6-9 deaths
    "{player} died {deaths} times. Maybe try a different strategy? Or any strategy at all?",
    "{deaths} deaths for {player}! They're not playing Valheim — Valheim is playing them.",
    "{player} hit {deaths} deaths tonight. Have they considered a nice peaceful game of solitaire?",
    "A whopping {deaths} deaths for {player}. At this rate Odin's mead hall needs an expansion.",
    "{player} died {deaths} times. The \"run back to your body\" simulator is strong with this one.",
]

SESSION_MESSAGES_EXTREME = [  # 10+ deaths
    "{player} died {deaths} times. This isn't gaming anymore, it's a cry for help.",
    "{deaths} deaths for {player}!? The respawn button is filing a restraining order.",
    "{player} set a record with {deaths} deaths. Their tombstones have their own zip code now.",
    "{player} died {deaths} times. Somewhere a Valkyrie just requested a transfer to a different game.",
    "{player} with {deaths} deaths! Even the trolls are saying \"maybe sit this one out, buddy.\"",
    "{deaths} deaths. {player} is speedrunning the afterlife at this point.",
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


def build_session_summary(session_deaths, session_players):
    """Build the end-of-session death leaderboard message."""
    if not session_players:
        return None

    # Include all players, even those with 0 deaths
    all_deaths = {p: session_deaths.get(p, 0) for p in session_players}
    leaderboard = sorted(all_deaths.items(), key=lambda x: (-x[1], x[0]))

    top_player, top_deaths = leaderboard[0]

    # Pick a witty message based on the top death count
    if top_deaths == 0:
        witty = random.choice(SESSION_MESSAGES_NONE)
    elif top_deaths <= 2:
        s = "s" if top_deaths != 1 else ""
        witty = random.choice(SESSION_MESSAGES_LOW).format(
            player=top_player, deaths=top_deaths, s=s
        )
    elif top_deaths <= 5:
        witty = random.choice(SESSION_MESSAGES_MED).format(
            player=top_player, deaths=top_deaths
        )
    elif top_deaths <= 9:
        witty = random.choice(SESSION_MESSAGES_HIGH).format(
            player=top_player, deaths=top_deaths
        )
    else:
        witty = random.choice(SESSION_MESSAGES_EXTREME).format(
            player=top_player, deaths=top_deaths
        )

    medals = ["🥇", "🥈", "🥉"]
    lines = ["📊 **Session Death Leaderboard**", ""]

    for i, (player, deaths) in enumerate(leaderboard):
        prefix = medals[i] if i < len(medals) else "💀"
        s = "s" if deaths != 1 else ""
        lines.append(f"{prefix} **{player}** — {deaths} death{s}")

    lines.append("")
    lines.append(f"*{witty}*")

    return "\n".join(lines)


def main():
    client = docker.from_env()
    try:
        container = client.containers.get("valheim")
    except docker.errors.NotFound:
        print("Error: 'valheim' container not found.", file=sys.stderr)
        sys.exit(1)

    players = dict(PLAYER_MAP)  # pre-fill with known mappings
    pending = []               # unknown SteamIDs awaiting name from ZDOID
    awaiting_zdoid = set()     # SteamIDs that connected but haven't loaded yet
    welcome_count = 0

    # Session tracking
    active_players = set()   # SteamIDs currently connected
    session_deaths = {}      # player_name -> death count this session
    session_players = set()  # player names who loaded in this session

    time.sleep(5)

    buffer = b""
    for chunk in container.logs(stream=True, follow=True, tail=0):
        buffer += chunk
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            line = line.decode("utf-8", errors="ignore").strip()

            # --- Player connected ---
            if "Got connection SteamID" in line:
                steamid = line.split()[-1]

                # New session if server was empty
                if not active_players:
                    session_deaths = {}
                    session_players = set()

                active_players.add(steamid)
                awaiting_zdoid.add(steamid)

                if steamid in players:
                    welcome_count += 1
                else:
                    pending.append(steamid)

            # --- Character ZDOID ---
            elif "Got character ZDOID from" in line:
                try:
                    after = line.split("Got character ZDOID from ")[1]
                    player_name, zdoid_str = after.split(" : ", 1)
                    player_name = player_name.strip()
                    zdoid_str = zdoid_str.strip()
                except Exception:
                    continue

                if zdoid_str == "0:0":
                    # Player died — track it and announce
                    session_players.add(player_name)
                    session_deaths[player_name] = session_deaths.get(player_name, 0) + 1
                    send_webhook(random_death_message(player_name))
                else:
                    # Initial character load or respawn after death
                    if pending:
                        steamid = pending.pop(0)
                        players[steamid] = player_name
                        awaiting_zdoid.discard(steamid)

                    if welcome_count > 0:
                        welcome_count -= 1
                        # Clear awaiting_zdoid for the matching known player
                        for sid in list(awaiting_zdoid):
                            if players.get(sid) == player_name:
                                awaiting_zdoid.discard(sid)
                                break
                        session_players.add(player_name)
                        send_webhook(f"✅ {player_name} has arrived!")

            # --- Player disconnected ---
            elif "Closing socket" in line:
                steamid = line.split()[-1]
                player_name = players.get(steamid, "Unknown Player")
                send_webhook(f"❌ {player_name} has dropped.")

                # Clean up if player disconnected before character load
                if steamid in pending:
                    pending.remove(steamid)
                if steamid in awaiting_zdoid:
                    awaiting_zdoid.discard(steamid)
                    if steamid in players:
                        welcome_count = max(0, welcome_count - 1)

                active_players.discard(steamid)

                # Last player left — post session leaderboard
                if not active_players and session_players:
                    summary = build_session_summary(session_deaths, session_players)
                    if summary:
                        send_webhook(summary)
                    session_deaths = {}
                    session_players = set()


if __name__ == "__main__":
    main()

