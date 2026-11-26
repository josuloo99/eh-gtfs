# Mugitu

Live map + next departures/arrivals for buses, trains, metro and trams across Euskal Herria (Euskadi, Nafarroa and
Ipar Euskal Herria), built on open GTFS and GTFS-RT feeds. The three areas are handled the same way: every operator
has a region (`eus`, `nav`, `ipar`) and the UI lists them side by side.

## Data sources

| Area | Source | Operators |
|---|---|---|
| Euskadi | Open Data Euskadi / MovEuskadi (`data-index.json`, read by `core.py`) | all of them (Euskotren, Bizkaibus, Lurraldebus, ...) |
| Ipar Euskal Herria | transport.data.gouv.fr (configured in `sources.py`) | Txik Txak |
| Ipar Euskal Herria | SNCF open data (GTFS) and its real-time feeds via transport.data.gouv.fr | SNCF trains: TER, Intercités, TGV (Hendaye, Biarritz, Bayonne, Cambo, Donibane Garazi...) |
| Nafarroa | Spanish Ministry's National Access Point, NAP (`sources.py`, needs `NAP_API_KEY`) | Interurbano de Navarra, Villavesas (Comarca de Pamplona) |
| Nafarroa | PDFs typed by hand (`feeds/`, see below) | La Baztanesa (Elizondo - Pamplona - Donostia) |
| Several areas | NAP and renfe.com | ALSA (NAP), Renfe Cercanias, Renfe Larga y Media Distancia |

Adding an operator outside the MovEuskadi index is one entry in `sources.py` (dataset id, resource ids, region and
optional quirks). Everything after that (import, real time, UI) is shared.

### La Baztanesa (no GTFS: transcribed from PDFs)

La Baztanesa publishes three scanned PDFs (https://www.labaztanesa.com/c_horarios.html), images without a text layer,
so there is nothing to download or parse. The timetable was read from the PDFs and typed once into
`feeds/labaztanesa.json`; `staticfeeds.py` turns it into a GTFS at import time and from there it is an operator like
any other (no real time).

- **Checkable:** `tables` repeats each printed table column by column (a `null` is a grey cell), so every row can be
  compared with the PDF by eye. `corrections` lists the two typos of the PDFs that were fixed (a swapped
  Arraioz/Irurita pair on Sunday evenings and a `21.10`), `known_discrepancies` the one cell on which two PDFs disagree.
- **Calendar:** "lunes a sábados laborables" and "domingos y festivos" as printed. The Sunday timetable also runs on the
  2026 holidays of Navarra, and there is no service on 25 December and 1 January. **The file is valid for 2026 only**
  (`validity.to`): when the operator publishes the next year, retype the changed rows, update `validity` and
  `calendar`, and the operator is re-imported on the next start (the import stamp is a hash of the files).
- **Mugaire is the transfer point** (green cells in the PDFs). Where two tables give identical times for the same
  stretch of road, it is stored once so a stop never lists one bus twice: Elizondo to Donostia is stored from Elizondo
  to Mugaire (the rest is the Pamplona to Donostia bus), Donostia to Pamplona from Mugaire to Pamplona (before that it is
  the Donostia to Elizondo bus). The `twin` fields name the table each was checked against; the times agree to the minute.
- **Stop positions** are not in the PDFs. Each stop has an `osm` reference and a `confidence`: *high* = an OpenStreetMap
  stop with that name or address (often mapped as "Parada de la Baztanesa"), *medium* = right place, exact side or
  position of the stop unknown (e.g. the clinic for "Ambulatorio Solchaga"), *low* = a guess among the OSM stops of the
  town (Lesaka-Puente, Bera-Aguerra). Coordinates come from OpenStreetMap contributors (ODbL).
- **Shapes** (`feeds/labaztanesa_shapes.json`) are the roads between the stops, drawn once with
  `python3 tools/make_shapes.py labaztanesa` (public OSRM server, OpenStreetMap roads) and committed; the app never
  calls the router. Run it again only when stops or patterns change.

To add another operator that only has PDFs: copy the structure of `feeds/labaztanesa.json`, add an entry with
`"static_feed": "<name>"` to `sources.py`, and run `tools/make_shapes.py <name>`.

### NAP (Nafarroa, ALSA)

`nap.transportes.gob.es` publishes timetables behind a personal API key. Get yours on the NAP site and give it to
the app in the environment variable `NAP_API_KEY`; it is never written in the code, the logs or `data/`:

    NAP_API_KEY=your-key python3 server.py            # local run
    echo 'NAP_API_KEY=your-key' >> .env               # Docker: .env next to docker-compose.yml (git ignores it)

How it works: the API (key sent in the `ApiKey` header) says which file is current for a dataset and when it was
updated; that date is the change stamp, so a timetable is downloaded again only when it changes. The download link
the API returns is pre-signed and expires after 15 minutes, so it is asked for just before downloading and fetched
without the key. Without a key (or with a wrong one) nothing new is downloaded, and the operators already imported
keep working; the log says `NAP_API_KEY is not set`.

Datasets: 963 Interurbano de Navarra (Gobierno de Navarra), 976 Villavesas (Infotuc), 932 ALSA. They have no
real-time feed. ALSA publishes one GTFS for all of Spain; only the trips that call inside Euskal Herria are kept
(whole lines, so their far ends appear too). The Interurbano feed has no trip headsigns, so each trip gets the town
of its last stop. Villavesas stops are named by street only (no town), as published.

### API keys (Txik Txak)

The Txik Txak feeds are hosted by Mecatran and need `?apiKey=...`, which may change. No key is stored in the code.
`sources.py` resolves the URLs from the portal at run time: it asks the dataset API of transport.data.gouv.fr for the
resources, follows the permanent data.gouv.fr link (a 302 that always points to the publisher's current keyed URL),
and falls back to the dataset's `original_url` and then to the last URLs that worked (`data/sources.json`).
They are resolved again every 30 minutes and immediately after a 401/403 from a feed or from the GTFS download
(at most once every 5 minutes per operator), so a rotated key heals itself.

### Txik Txak real-time quality

The portal's validator reports thousands of errors on this GTFS-RT feed; checked against the live feed:

- The validator's "times must increase" error (E022) and the missing `vehicle_id` are harmless here.
- The feed publishes an update for every trip of the day, tracked or not. A bus that is really followed has a delay
  that is never exactly 0 s and stays constant along the trip; about half of the trips have exactly 0 s on every
  stop, which is just the timetable. Those are not shown as "live" and draw no vehicle; only their SKIPPED stops are
  kept.
- SKIPPED stops are mostly real: they match the roadworks/detours of the alerts feed (same stops skipped by every
  trip of the line). They are shown as "Stop not served", not as a cancelled trip.
- An arrival/departure pair where one event is hours off and the other is sane (seen: -3.8 h) uses the sane one.
- There is no vehicle-position feed, so buses are placed from the trip updates and drawn dashed, like Euskotren.
  The trips without live data are drawn from the timetable (theoretical vehicles).

### SNCF trains (Ipar Euskal Herria)

SNCF publishes one GTFS for the whole of France (`Export_OpenData_SNCF_GTFS_NewTripId.zip`, whose trip ids match the
real-time feeds) and national GTFS-RT trip updates and service alerts (through `proxy.transport.data.gouv.fr`). It is
configured like Renfe, as a national feed (`store.BBOX_AGENCIES`): the importer keeps only the trips with a stop inside
Euskal Herria (about 960 trips: Bordeaux - Dax - Bayonne - Hendaye, Bayonne - Cambo - Donibane Garazi, Bayonne - Pau,
Paris - Hendaye...) and the real-time entities are cut to them.

- `trip_headsign` is the train number, so every trip gets the name of its last stop as destination
  (`headsign_last_stop`); a few night trains have no route name (`INCONNU`) and are named "first stop → last stop".
- The feed has no vehicle positions and lists a trip with 0 s delays when it has nothing to say (it reports disruptions
  only), so trains with only zero delays count as untracked (`zero_delay_untracked`, as for Txik Txak): they are drawn
  from the timetable (theoretical vehicles), and only delayed or cancelled ones are live / estimated. Estimated
  positions run in a straight line between stations (the GTFS has no shapes) and only inside Euskal Herria.

## Run

    python3 server.py            # http://127.0.0.1:8000  (use --host 0.0.0.0 --port N to change)

Python 3.9+ standard library only, no pip install needed. On first start the server downloads every
operator's GTFS zip and builds SQLite databases in `data/db/` (about 40 s). It refreshes them when the
index (`data-index.json`) reports a newer timetable. Real-time `.pb` feeds are fetched on demand
(15 s cache) and decoded by a built-in protobuf reader (`gtfsrt.py`).

## Notes

- A backend is required: the opendata hosts send no CORS headers and the `.pb` files need decoding.
- Many operators publish empty feeds (15-byte files). The UI shows "scheduled" for those.
- Euskotren publishes trip updates but no vehicle positions: train positions are estimated from
  the trip updates and shown with a dashed outline.
- Vehicles on the map come in three kinds (`kind` in `/api/vehicles`), most to least eye-catching:
  `gps` (real position from the operator: solid pill with a coloured ring), `est` (estimated from live
  arrival data, Euskotren / Lurraldebus / Txik Txak: dashed outline) and `sched` (operator without any live data,
  e.g. Navarra interurban: position computed from the timetable only, drawn faded with a dotted
  outline below the others; zoomed out, the count bubbles include every kind alike). Each kind can be shown or hidden in the Filters tab.
- AlavaBus encodes entity timestamps as local time; `LOCAL_EPOCH` in `core.py` corrects this.
- The Renfe feeds cover all of Spain; see "Limited to Euskal Herria" below.
- Renfe's servers give the same file slightly different `Last-Modified` / `ETag` values (seconds apart), so a file
  counts as new only when its date differs by more than 10 minutes or its size changes (`sources._same_file`);
  otherwise every start would download and import it again.

## Cache busting

`index.html` is rendered by the server: every local css / js / image / manifest it references gets
`?v=<hash of the file's content>`, so a changed file gets a new URL and browsers fetch it again. Versioned URLs are
served `Cache-Control: public, max-age=31536000, immutable`; `index.html`, `sw.js` and any URL without the current
hash are always revalidated (ETag, `304 Not Modified` when unchanged); `/api/*` is `no-cache` (not `no-store`, which
would keep the page out of the back/forward cache). Nothing to do on deploy, the hashes are computed from the files at
run time. The service worker serves versioned files cache first (they never go stale; instant and offline) and
everything else network first, and keeps only the newest version of each file.

## Security headers

Every response carries `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
`Permissions-Policy` (only geolocation, for "nearby stops"), `X-Frame-Options: DENY` and
`Cross-Origin-Opener-Policy: same-origin`; `/api/*` also `Cross-Origin-Resource-Policy: same-origin`, and
`Strict-Transport-Security` when the reverse proxy says the request was HTTPS (`X-Forwarded-Proto`).

The page has a Content-Security-Policy built when `index.html` is rendered (`server.csp_for`): scripts only from this
origin, the external scripts the page itself loads (analytics) and its inline scripts **by hash**, so editing an
inline script needs no change; styles only as attributes, no `<style>` blocks; images and requests only to this origin,
OpenFreeMap and OpenStreetMap tiles; workers from `blob:` (MapLibre); no framing; no plugins. If you add another
external host (a tile server, an API) add it to `MAP_HOSTS` / `RASTER_HOSTS` in `server.py`, or the browser blocks it
(the console shows the violation).

## Colour scheme

The page follows the system's light/dark setting. The theme button pins `light` or `dark` only when that differs
from the system; pressing it again returns to "follow the system" (nothing stored). The choice is mirrored in
`<meta name="color-scheme">` and applied before first paint by a small inline script in `index.html`.

## Map

Two basemaps, chosen in the Filters tab:

- **Simple** (default): [OpenFreeMap](https://openfreemap.org) vector tiles, free and without an API key. The style
  follows the theme: **Positron** in the light theme, **Fiord** in the dark one. Place names are in **Basque**: the
  tiles carry every OpenStreetMap language as `name:xx`, and `static/app.js` (`basqueLabels`) changes the style's label
  expressions from the English name to `name:eu`, falling back to the local name where a place has no Basque name
  (so the labels are only as Basque as OpenStreetMap is: Iruñea, Baiona, Miarritze, Jaka, Tutera, but Bilbao, whose
  `name:eu` in OSM is "Bilbao"). The language of these labels is fixed and does not follow the interface language.
- **Detailed**: the standard OpenStreetMap raster tiles (dark theme: inverted).

The app draws the map with Leaflet; vector tiles are drawn by MapLibre GL inside it through the official
[`@maplibre/maplibre-gl-leaflet`](https://github.com/maplibre/maplibre-gl-leaflet) binding. Both are vendored in
`static/vendor/maplibre/` (maplibre-gl 5.24.1, binding 0.1.4, pinned; the 5.x line is used because 6.x is ES-module only
and this app has no bundler). To update, download the same files from the same npm paths. The style is fetched from
`tiles.openfreemap.org/styles/{positron,fiord}` when the map starts; changing theme swaps the style on the same map.
If the browser has no WebGL or OpenFreeMap cannot be reached, the map falls back to the OpenStreetMap raster tiles.
The dark style (Fiord) draws a few lighter rectangles over the open sea; they also appear with plain MapLibre and no code of this app, so they come from OpenFreeMap's style or data.

## Zoom levels

All kinds of stops (bus, train, metro, tram, funicular) appear at the same zoom, 13. Live vehicles are drawn one by
one from zoom 10; zoomed further out they are grouped into count bubbles (click one to zoom in), so the opening
view of the whole territory shows where the service is running. Picking a line, a trip or up to three operators
shows their vehicles one by one at any zoom. The thresholds are `STOP_MIN_ZOOM` and `VEHICLE_MIN_ZOOM` in
`static/app.js`.

## Stops on the map

A stop is a dot coloured by its mode (bus, train, metro, tram, funicular); rail stops are slightly larger. In a
stop's panel, the line chips work like the transport-mode chips: nothing picked shows every line, picking one shows
only it, picking more adds them (live and by date) whenever two or more lines call there.

## Limited to Euskal Herria

Everything shown is limited to Euskal Herria (outline: OpenStreetMap relation 11107464, simplified to about
1000 points in `region.py`; `python3 tools/make_region.py` rebuilds it). The rule is applied to every operator
when its timetable is imported: **a trip is kept only if at least one of its stops is inside the territory**.
A trip that is kept keeps all its stops, so a line that leaves the territory still shows where it goes; a line
whose stops are all outside is not stored, so it appears nowhere (map, lines, search, departures, alerts).
Real-time entities (vehicles, trip updates, alerts) of the Renfe national feeds, or of any operator with cut
trips, are filtered to the kept trips, lines and stops. An operator with nothing inside is reported as
"no stops inside Euskal Herria" in the Sources tab. The border is approximate (a couple of hundred metres).
Changing `store.IMPORT_TAG` re-imports every operator, the old database serving until the new one is ready.

## Timetable for another date

The station and line views have a date bar at the top. In a station, today means live data; picking
another date shows that day's theoretical timetable (no real-time data is merged). The line view
always shows the timetable of its date (today by default); trips opened from it show the same date.
The selectable range is today minus `SCHEDULE_PAST_DAYS` (default 7) to today plus `SCHEDULE_FUTURE_DAYS`
(default 60), narrowed to the period each operator's published GTFS covers (calendar and calendar_dates),
so it is often shorter, e.g. Euskotren publishes about 6 weeks.
API: `/api/departures?...&date=YYYYMMDD`, `/api/route_schedule?agency&route&date`, `/api/trip?...&sched=1`.

## Lurraldebus live arrivals

The seven "(Lurraldebus)" operators in Gipuzkoa publish empty GTFS-RT feeds, but lurraldebus.eus has a
real-time page per stop (`https://lurraldebus.eus/real/result/0/<stop_id>`, same stop ids as the GTFS). It lists
the next bus of every line with minutes left and the occupancy reported by the vehicle. `lurraldebus.py` reads it
(`core.py`, section "Lurraldebus live arrivals", does the rest):

- Both Renfe timetables are read straight from Renfe, not from the MovEuskadi copy: Cercanias
  (`ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip`) and long/medium distance
  (`ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip`, Alvia/Intercity/Regional/Avant; no high speed
  reaches Euskal Herria). Long-distance lines have no name in the feed, so they are named
  "first stop → last stop". Only Cercanias has real time: Renfe's national feeds (`gtfsrt.renfe.com`:
  vehicle positions, trip updates, alerts), set in `sources.py` next to the static GTFS.
- Each prediction is matched to the scheduled trip it most likely belongs to (same line, closest scheduled time,
  same direction) and stored as a synthetic trip update. Station departures then show live times, trip pages show
  the delay carried to the other stops, and buses appear on the map as estimated (dashed) vehicles, like Euskotren.
- The page has no trip id, so the match is an inference. On lines with a long headway a very late bus can be
  attributed to the wrong trip (its position stays right, its "late/early" label may not).
- Occupancy is the number of passengers on board, as published by the site.
- Destinations use the site's wording (learned per line and direction), not the lowercase GTFS route name.
- "Drop-off only" / "Pick-up only" stops are flagged.
- A stop with no information, or the site being down, simply falls back to the timetable.

Keeping the load on lurraldebus.eus low (the page is ~400 kB, ~60 kB gzipped, and the only way to get one stop):

- One shared cache and one request per stop at a time, whatever the number of users: 30 s for a stop somebody
  opened, 100 s for the map tracker, 2 min for "no information" answers.
- A stop view only calls the site when the timetable has a bus there in the next ~75 minutes.
- The map tracker runs only while a client shows buses (zoom >= 11, or a line/operator filter) and only covers
  trips that reach the visible area. It picks the fewest stops that see every active trip (greedy set cover),
  e.g. roughly 20 stops for a city view and 58 for the whole province, refreshed every 2 minutes at most.
- Token bucket (default 1 request/s, 2 parallel connections) with part of the budget reserved for users, so the
  tracker never delays someone opening a stop. Circuit breaker with exponential back-off (and `Retry-After`)
  when the site fails; data up to 5 min old is served meanwhile. A page layout change is detected and treated as
  a failure instead of "no buses".

Settings (optional environment variables, e.g. under `environment:` in `docker-compose.yml`):
`LURRALDEBUS_LIVE=0` disables everything, `LURRALDEBUS_TRACK=0` disables only the map tracker,
`LURRALDEBUS_RATE` (requests/s, default 1.0) and `LURRALDEBUS_MAX_STOPS` (default 60) tune the limits. The Info tab shows the source status per
operator.

## Old GPS fixes (Dbus, Bizkaibus)

The Open Data Euskadi vehicle feeds are written well after the GPS fixes are taken. For Dbus the feed is rebuilt about
once a minute and each bus reports about every 90 s, so a position is between 100 s and 215 s old when the app gets
it (about 2.5 minutes on average); in a city that is 400 m or more. Its trip updates carry only the next stop and a
delay that is almost always 0, so they add no arrival times.

`core.advance_fix` moves each fix forward along the bus's route (the trip's shape) by the age of the fix, following the
timetable: the point where the bus was seen becomes a scheduled time, that time is advanced by the age of the fix,
and the schedule gives the position. The bus must be on its route (within 120 m) and between the stops around the one
it is heading to; the move is limited to 240 s. Buses that do not match (no shape, off route) stay where they were
reported. The vehicle card says when a position was moved, and by about how much; the time shown is still the fix's.

Measured on 339 pairs of real Dbus fixes (a fix predicted from an earlier one of the same bus): without the
correction the shown bus was a median 409 m behind the real one along its route and 344 m away in a straight line
(90th percentile 654 m); with it the bias is about 0 m and the median error about 100 m (90th percentile 300 m).
Limiting how many stops ahead a bus may be moved made it worse, so there is no such limit. Checked again later on 906
more pairs (fix ages 60-215 s): median error 91 m, 90th percentile 286 m, against 360 m and 710 m for the unmoved
fix; adding a dwell time per stop (5-45 s) to the timetable does not help (equal or worse), so none is used.

Dbus's own website estimates the arrival at a stop (`admin-ajax.php?action=calcula_parada`, POST, with a `security`
nonce that the line pages embed, an internal `parada` id per stop from each line's `<n>markers.xml`, and a session
cookie). It answers one stop per request (1-4 s each) with the next bus of every line, in whole minutes. It was
compared with the correction above on 463 estimates, against when the buses really reached the stop (from their later
fixes): for buses 0-5 minutes away the estimate is better by about 15 s at the median (30 s against 45 s); from 6 to 12
minutes it is about the same, and beyond 12 minutes it is just the timetable (median error 19 minutes). Covering every
bus would take one request per active stop, which is too much for that site (it is a WordPress admin endpoint, and
it prints its own SQL in the answer), for a gain of about 60 m. So it is **not** used for the map. If someone wants
live "next bus" times in the stop view (the estimate is good there), it would be done like the Lurraldebus arrivals.

It is enabled for Dbus and Bizkaibus (Bizkaibus: snapshots 130-215 s old; not moved the median error is about 700 m,
advanced 450 m). Other feeds of the same publisher are as old (Metro Bilbao 150 s, Alavabus 120 s, Tuvisa 95 s; Renfe
11 s) and could be added. `ADVANCE_FIXES=dbus,bizkaibus,...` changes the operators, `ADVANCE_FIXES=none` turns it off.

### Bizkaibus: positions from the stop arrival service

Bizkaibus publishes one snapshot of all its buses (a single timestamp), rebuilt about every two minutes, and numbers
the vehicles of each snapshot afresh (`<snapshot time>_<n>`), so the ids change every time: the app identifies a bus by
its trip instead (stable markers, and no junk label). Advancing the snapshot along the timetable is not enough for
buses that run fast on long stretches, but bizkaia.eus has a service that tells, for a stop, how many minutes **and
metres** the next two buses of every line still have to travel (`bizkaibus.py`, no key, 0.5 s per answer). The metres
place the bus on its route right now.

- **Matching.** The answer has no bus id: the line's buses before the stop are taken from the latest snapshot in the
  order of their distance to it, and the first bus listed is the first of them that has not already gone by (a bus
  cannot move backwards) and could have got there at a possible speed (28 m/s) since its snapshot; the second listed is
  the next one. A match becomes an observation (`trip`, metres along the route, time) that is advanced along the
  timetable by its age for as long as it is at most 90 s old; after that, or without one, the snapshot is advanced as
  for Dbus. The vehicle card says which one was used.
- **Who is asked.** Only while a client shows buses on the map (the same map areas the Lurraldebus tracker follows),
  only about buses in view, and the fewest stops that show them: stops 350 m to 8 km ahead of each bus, chosen greedily
  by how many buses they reveal (two per line). A city view needs about 50 stops per round (about 8 buses per request
  for the best ones). No request is made when nobody is looking. Requests are rate limited (`BIZKAIBUS_RATE`, default
  1.5 per second for everybody, two at a time), a stop is not asked again within 25 s, and repeated failures pause the
  client (circuit breaker). `BIZKAIBUS_LIVE=0` turns the whole thing off. The stop code is the GTFS `stop_id` **padded
  to four digits** (`0307`; `307` is "unknown").
- **Measured.** The tracker was run for 20 minutes with a Bilbao view (1,227 requests, no errors) and every answer and
  snapshot recorded and replayed. At the fix time of each later snapshot, the position the app would have shown was
  compared with where the bus really was (1,393 comparisons): median error 159 m (90th percentile 495 m) with the stop
  service, against 332 m (1,031 m) for the snapshot advanced along the timetable, and 640 m (1,800 m) for the snapshot
  as published. Only 0.6% of the buses were more than 1.5 km off. An observation older than 90 s is no better than the
  advanced snapshot, which is why it is not used for longer. A rule rejecting matches that travelled far more than the
  timetable allows made no difference, so there is none.
- **Cost.** A vehicle list takes about 50 ms more to build (0.05 s to 0.10 s). The stop service also gives live
  arrival minutes for the stop view; that is not used yet.

## Villavesas live GPS

Villavesas (Comarca de Pamplona) publishes no GTFS-RT, but its web map (tuvillavesa.es/eu/interactive-map) shows
live buses from a SIRI-VM service, one request per line (`villavesa.py`). The positions are real GPS, so they are
drawn as `gps` vehicles, like Bizkaibus or Dbus.

- The service needs a bearer token (a JWT valid for 5 minutes). The web page gets it from a Next.js server action
  without any login; `villavesa.py` calls the same action when it needs a token. Nothing is configured or stored.
  The action is identified by a hash that changes when the site is rebuilt: when it stops answering, the page's
  scripts are scanned for hashes and each one is tried until one returns a JWT.
- Each `VehicleJourneyRef` is the GTFS `trip_id` of the NAP dataset, so a bus is tied to its scheduled trip (trip
  page, headsign, route shape). Lines that are not in that GTFS (R1-R5 on match days, A to the airport) are drawn
  with the name and colour the service publishes. SIRI sends no heading: it is taken from the bus's movement, or
  from the direction of the trip's route at that point.
- Being polite to their server: nothing is requested while nobody uses the app, the result is shared by all
  clients and refreshed in the background every 30 s at most, only the lines with a trip scheduled now are asked
  for (about 25 by day, a few at night), 3 requests run at once, and the lines the GTFS lacks are asked for less
  often when they are empty. If the service fails, the last positions are kept for 90 s and then the operator goes
  back to theoretical (timetable) positions.
- Positions are therefore up to about a minute old. Optional environment variables: `VILLAVESA_LIVE=0` turns it
  off, `VILLAVESA_TTL` (seconds, default 30) changes the refresh period.

## Docker

The image is built by GitHub Actions (`.github/workflows/docker.yml`) on every push to `master` and published to
the GitHub Container Registry as `ghcr.io/josuloo99/mugitu` (the name is fixed, whatever the repository is called)
for `linux/amd64` and `linux/arm64` (so it runs on a Raspberry Pi too). Tags: `latest` (master), `sha-<commit>`
(every push) and `1.2.3` / `1.2` for git tags like `v1.2.3`.

Run it anywhere, without cloning the code or building anything, with just `docker-compose.yml` (no `.env`
needed):

    docker compose up -d             # pulls the image, http://localhost:8000
    docker compose pull && docker compose up -d    # update to the latest image

The first start imports all timetables (about a minute); they are kept in the `mugitu-data` volume.
To use another port, change the left number in `ports:`. The container runs as `APP_UID:APP_GID` (default
1000:1000); only if you replace the `mugitu-data` volume with a host folder, set them in a `.env` next to the
compose file to your own ids (the output of `id -u` and `id -g`, e.g. `APP_UID=1000`, `APP_GID=1000`) and make the folder writable by them.
The container needs outbound HTTPS access to
opendata.euskadi.eus, transport.data.gouv.fr, app.mecatran.com and, in the browser, tiles.openfreemap.org and tile.openstreetmap.org. Put a reverse proxy (Caddy, nginx, Traefik) in
front for HTTPS if you expose it publicly; installing the app on a phone requires HTTPS.

First publish: GitHub keeps a new package private. After the first workflow run open the repository's
Packages, then mugitu, then Package settings and set the visibility to Public (or run `docker login ghcr.io`
with a token that has `read:packages` on the machine that pulls). In the repository settings, Actions must be
allowed to write packages (Settings, Actions, General, Workflow permissions).

To build from your own checkout instead (for example while changing the code):

    docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build

## Install as an app (phone)

The UI is a Progressive Web App: it has a manifest (`static/manifest.webmanifest`), icons and a service
worker (`static/sw.js`) that keeps the app shell available offline. Live data and map tiles still need a connection.

- Android / Chrome: open the site, then use the "Install app" button in the Info tab (or the browser menu, "Install app").
- iPhone / Safari: Share, then "Add to Home Screen".

It opens full screen with the Mugitu name and icon. Installing and the service worker require HTTPS
(or `localhost`), so put a reverse proxy with a certificate in front when you expose it publicly.
The icon sources are `static/icon.svg` (rounded) and `static/icon-maskable.svg`; the PNGs were rendered from them
with `rsvg-convert -w <size> -h <size>`.
