#!/usr/bin/env python3
"""KDE Connect phone media playback logger.

Watches KDE Connect MPRIS bus names on the session bus and records phone
media playback sessions into a SQLite database with fields:
app, title, description, url, start, end, duration_seconds

A session opens when a phone player reports Playing and closes when it stops
playing, when the player disappears, or when the service shuts down. If the
same media (same app and title) resumes later on the same calendar day (in
the service timezone) with no other media recorded in between, the last
database row is updated instead of a new one being inserted, so morning +
evening listening produces a single row while A -> B -> A produces three.

A CSV export with columns
app, title, description, url, start, end, duration_seconds
is written (overwritten) on SIGUSR1.

Environment:
  KMV_TZ        IANA timezone for calendar-day boundaries and timestamps
                (default: system local timezone)
  KMV_DB_PATH   SQLite database path (default: ~/.local/state/kdeconnect-media/media_log.db)
  KMV_CSV_PATH  CSV export path (default: ~/.local/state/kdeconnect-media/media_log.csv)
"""

import csv
import datetime
import os
import signal
import sqlite3
import sys
from zoneinfo import ZoneInfo

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

MPRIS_PREFIX = "org.mpris.MediaPlayer2.kdeconnect"
MPRIS_PATH = "/org/mpris/MediaPlayer2"
ROOT_IFACE = "org.mpris.MediaPlayer2"
PLAYER_IFACE = ROOT_IFACE + ".Player"
CSV_HEADER = ["app", "title", "description", "url", "start", "end", "duration_seconds"]
DESC_KEYS = ("xesam:comment", "xesam:description", "xesam:subtitle")
POLL_INTERVAL_SECONDS = 2
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS media_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    start TEXT NOT NULL,
    end TEXT NOT NULL,
    duration_seconds REAL NOT NULL
)
"""

if os.environ.get("KMV_TZ"):
    TIMEZONE = ZoneInfo(os.environ["KMV_TZ"])
else:
    TIMEZONE = datetime.datetime.now().astimezone().tzinfo
STATE_DIR = os.path.join(
    os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")),
    "kdeconnect-media",
)
DB_PATH = os.environ.get("KMV_DB_PATH", os.path.join(STATE_DIR, "media_log.db"))
CSV_PATH = os.environ.get("KMV_CSV_PATH", os.path.join(STATE_DIR, "media_log.csv"))

proxies = {}
sessions = {}
last_seen = {}
main_loop = None
session_bus = None
db = None


def now():
    return datetime.datetime.now(TIMEZONE)


def fmt(moment):
    return moment.isoformat(timespec="seconds")


def parse_ts(text):
    return datetime.datetime.fromisoformat(text)


def unpack(value):
    if isinstance(value, GLib.Variant):
        return value.unpack()
    return value


def log_line(text):
    print(fmt(now()), text, flush=True)


def parse_identity(identity):
    if " - " in identity:
        app, device = identity.rsplit(" - ", 1)
    else:
        app, device = identity, ""
    return app, device


def metadata_fields(meta):
    title = meta.get("xesam:title") or ""
    description = ""
    for key in DESC_KEYS:
        value = meta.get(key)
        if value:
            description = value if isinstance(value, str) else ", ".join(str(item) for item in value)
            break
    url = meta.get("xesam:url") or ""
    return title, description, url


def open_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(DB_SCHEMA)
    connection.commit()
    return connection


def last_session():
    return db.execute(
        "SELECT id, app, title, start FROM media_sessions ORDER BY id DESC LIMIT 1"
    ).fetchone()


def can_merge(session, end, previous):
    same_media = previous[1] == session["app"] and previous[2] == session["title"]
    same_day = parse_ts(previous[3]).date() == session["start"].date() == end.date()
    return same_media and same_day


def write_row(session, end):
    start = session["start"]
    duration = round((end - start).total_seconds(), 1)
    previous = last_session()
    assert start <= end
    if previous is not None and can_merge(session, end, previous):
        start = parse_ts(previous[3])
        duration = round((end - start).total_seconds(), 1)
        db.execute(
            "UPDATE media_sessions SET description = ?, url = ?, end = ?, duration_seconds = ? WHERE id = ?",
            (session["description"], session["url"], fmt(end), duration, previous[0]),
        )
    else:
        db.execute(
            "INSERT INTO media_sessions (app, title, description, url, start, end, duration_seconds)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session["app"], session["title"], session["description"], session["url"], fmt(start), fmt(end), duration),
        )
    db.commit()
    log_line(f"recorded: {session['app']}, {session['title']}, {fmt(start)} .. {fmt(end)} ({duration}s)")


def close_session(bus, end):
    session = sessions.pop(bus)
    write_row(session, end)


def open_session(bus, app, title, description, url, start):
    sessions[bus] = {"app": app, "title": title, "description": description, "url": url, "start": start}
    log_line(f"playing: {app} | {title}")


def apply_snapshot(bus, status, meta, identity):
    title, description, url = metadata_fields(meta)
    app, _device = parse_identity(identity)
    state = (status, title)
    if last_seen.get(bus) == state:
        return
    last_seen[bus] = state
    if status == "Playing" and title:
        current = sessions.get(bus)
        if current is not None and (current["app"] != app or current["title"] != title):
            close_session(bus, now())
            current = None
        if current is None:
            open_session(bus, app, title, description, url, now())
    elif bus in sessions:
        close_session(bus, now())


def player_snapshot(player, root):
    return (
        unpack(player.get_cached_property("PlaybackStatus")) or "Stopped",
        unpack(player.get_cached_property("Metadata")) or {},
        unpack(root.get_cached_property("Identity")) or "",
    )


def on_properties_changed(_proxy, changed, _invalidated):
    changed = unpack(changed)
    if "PlaybackStatus" not in changed and "Metadata" not in changed:
        return
    bus = _proxy.get_name()
    entry = proxies.get(bus)
    if entry is None:
        return
    apply_snapshot(bus, *player_snapshot(entry[0], entry[1]))


def on_name_owner_changed(_bus, _sender, _path, _iface, _signal, params):
    name, _old, new = unpack(params[0]), unpack(params[1]), unpack(params[2])
    if not name or not name.startswith(MPRIS_PREFIX):
        return
    if new:
        add_player(name)
    else:
        remove_player(name)


def add_player(bus):
    if bus in proxies:
        return
    try:
        player = Gio.DBusProxy.new_sync(session_bus, Gio.DBusProxyFlags.NONE, None, bus, MPRIS_PATH, PLAYER_IFACE, None)
        root = Gio.DBusProxy.new_sync(session_bus, Gio.DBusProxyFlags.NONE, None, bus, MPRIS_PATH, ROOT_IFACE, None)
    except GLib.Error as err:
        log_line(f"proxy error for {bus}: {err}")
        return
    player.connect("g-properties-changed", on_properties_changed)
    proxies[bus] = (player, root)
    apply_snapshot(bus, *player_snapshot(player, root))


def remove_player(bus):
    if bus in sessions:
        close_session(bus, now())
    proxies.pop(bus, None)
    last_seen.pop(bus, None)


def poll_once():
    for bus, (player, root) in list(proxies.items()):
        apply_snapshot(bus, *player_snapshot(player, root))
    return True


def request_export(*_args):
    try:
        export_csv()
    except (OSError, sqlite3.Error) as err:
        log_line(f"csv export failed: {err}")
    return GLib.SOURCE_CONTINUE


def export_csv():
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADER)
        writer.writerows(
            db.execute(
                "SELECT app, title, description, url, start, end, duration_seconds"
                " FROM media_sessions ORDER BY id"
            )
        )
    log_line(f"exported: {CSV_PATH}")


def request_shutdown(*_args):
    for bus in list(sessions):
        try:
            close_session(bus, now())
        except (OSError, sqlite3.Error) as err:
            log_line(f"failed to record session on {bus}: {err}")
    log_line("shutdown: all open sessions closed")
    main_loop.quit()
    return GLib.SOURCE_REMOVE


def list_mpris_names():
    result = session_bus.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "ListNames",
        None,
        GLib.VariantType.new("(as)"),
        Gio.DBusCallFlags.NONE,
        -1,
        None,
    )
    return [unpack(name) for name in result[0] if unpack(name).startswith(MPRIS_PREFIX)]


def watch_signals():
    try:
        gi.require_version("GLibUnix", "2.0")
        from gi.repository import GLibUnix

        for sig in (signal.SIGTERM, signal.SIGINT):
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, sig, request_shutdown, None)
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, request_export, None)
    except (ImportError, AttributeError):
        for sig in (signal.SIGTERM, signal.SIGINT):
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, request_shutdown, None)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, request_export, None)


def main():
    global main_loop, db, session_bus
    db = open_db()
    session_bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    session_bus.signal_subscribe(
        None,
        "org.freedesktop.DBus",
        "NameOwnerChanged",
        "/org/freedesktop/DBus",
        None,
        Gio.DBusSignalFlags.NONE,
        on_name_owner_changed,
    )
    for bus in list_mpris_names():
        add_player(bus)
    GLib.timeout_add_seconds(POLL_INTERVAL_SECONDS, poll_once)
    watch_signals()
    log_line(f"started: db={DB_PATH} csv={CSV_PATH} tz={TIMEZONE}")
    main_loop = GLib.MainLoop()
    try:
        main_loop.run()
    except KeyboardInterrupt:
        request_shutdown(signal.SIGINT, None)
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
