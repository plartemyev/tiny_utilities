KDE Connect phone media playback logger
========================================

Records what is played on an Android phone paired with KDE Connect into a
SQLite database: which phone app played it, media title, description and URL
when the player reports them, playback start and end (ISO 8601, tz-aware
local time) and wall-clock duration in seconds.

The service watches KDE Connect MPRIS bus names (`org.mpris.MediaPlayer2.kdeconnect.*`)
on the session DBus. Each phone media player gets its own bus name; the
`Identity` property carries the phone-side app name (e.g. `Fennec - Raptor LTD`),
`Metadata` carries the track info. Desktop notifications are not used.

Database
--------
SQLite table `media_sessions`:
`id, app, title, description, url, start, end, duration_seconds`

- `app` - phone-side player name (Fennec, YouTube, ...), from MPRIS `Identity`;
- `description`, `url` - usually empty, filled from `xesam:comment` /
  `xesam:description` / `xesam:url` when a player reports them;
- `start` / `end` - local ISO 8601 timestamps with UTC offset;
- `duration_seconds` - wall-clock `end - start`.

CSV export
----------
Sending SIGUSR1 to the service overwrites the CSV export file (header row
plus all rows from the database, ordered by `id`):

    kill -USR1 $(pgrep -f kdeconnect_media_logger.py)

Columns: `app, title, description, url, start, end, duration_seconds`.
The CSV is NOT updated automatically on playback - only on SIGUSR1.

Concatenation of interrupted playback
-------------------------------------
If playback of a media stops and the same media (same app + same title)
resumes later, no new row is inserted: the last database row is updated so
that `start` is the first start and `end` is the last end. A row is merged
only when no other media was recorded in between and everything happened on
the same calendar day in the service timezone. So playing A in the morning
and in the evening yields one row, while A -> B -> A yields three.

REQUIREMENTS
------------
* Python 3.9+ (`zoneinfo`, `sqlite3`);
* PyGObject (`gi.repository.Gio`) - on Arch Linux: `python-gobject` package;
* KDE Connect daemon (`kdeconnectd`) running in the user session.

USAGE
-----
Install as a systemd user service:

    install -Dm755 kdeconnect_media_logger.py ~/.local/bin/kdeconnect_media_logger.py
    install -Dm644 kdeconnect-media-logger.service ~/.config/systemd/user/kdeconnect-media-logger.service
    systemctl --user daemon-reload
    systemctl --user enable --now kdeconnect-media-logger.service

Database defaults to `~/.local/state/kdeconnect-media/media_log.db`,
CSV export to `~/.local/state/kdeconnect-media/media_log.csv`.

Configuration (environment, e.g. via a systemd drop-in):

* `KMV_TZ` - IANA timezone used for calendar-day merge boundaries and for
  timestamp formatting (default: system local timezone);
* `KMV_DB_PATH` - SQLite database path (default as above);
* `KMV_CSV_PATH` - CSV export path (default as above).

NOTES
-----
* If playback is already running when the service starts, the session is
  recorded starting from the service start time.
* Pauses are not recorded as separate rows: pause + resume of the same media
  is merged into a single row (see above).
* A media session that is still open when the service is killed uncleanly
  (crash, power loss) is not written to the database.
* `mpris:trackid` exposed by KDE Connect is a constant `/org/mpris/MediaPlayer2`
  for phone players and is therefore not used for track identity; `xesam:title`
  is used instead.
* On KDE Connect remote MPRIS players `Position` is always `-1000` (unknown),
  so positions are not recorded.

LICENSE
-------
This is free software, distributed under the GPL v.2.
