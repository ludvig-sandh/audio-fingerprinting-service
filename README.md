# Audio Fingerprinting Service

This project implements an audio fingerprinting and matching service inspired by techniques used in systems like Shazam. I based the matching algorithm on the paper by Wang, Avery Li-Chun, "An Industrial-Strength Audio Search Algorithm" (ISMIR 2003). The project includes a FastAPI backend for inserting and identifying songs, and a lightweight frontend example for recording audio and testing matches.

Deploy by cloning the repository, building the Docker image, and running the container.

## Demo

Live demo: `https://ludvig-sandh.github.io/audio-fingerprinting-service/`

I deployed the system on a cheap server and inserted a small set of songs so anyone can test the system through the link above. As a Swede, I thought ABBA songs were fitting.

## Scalability

This demo currently runs on a very low-cost server. Based on current memory use and query behavior, I estimate that moving to a stronger instance (for example, 16 GB RAM) should reasonably support on the order of 10,000 songs in a single-node setup.

To scale into the millions of songs, the main design shift is to employ sharding to partition the fingerprints across multiple nodes and route each query hash to the responsible shard. In that architecture:

- each shard stores only part of the hash space
- query work is parallelized across shards
- capacity grows horizontally by adding nodes
- a lightweight aggregation layer combines shard-level vote results into a final match

For this demo, SQLite keeps the setup simple, but it is not ideal for large-scale distributed workloads. At higher scale, the storage layer should move to a system designed for concurrent writes, partitioning, and horizontal growth (for example PostgreSQL with partitioning, or a distributed key-value/index store for fingerprint hashes). This would enable sharding the fingerprint index cleanly and sustaining much higher query throughput.

## Repository Layout

- `backend/` - FastAPI service, fingerprinting logic, and SQLite storage.
- `docs/` - Static frontend (HTML/CSS/JS) for recording and identification, served by GitHub Pages.

## Backend Overview

The backend:

- extracts fingerprints from audio
- stores song metadata and fingerprints in SQLite
- matches a short sample against stored fingerprints

### Key Limits

- Inserted songs must be **1-5 minutes** long
- Identify samples must be **≤ 15 seconds**
- Maximum number of songs can be capped via `MAX_SONGS` (unset by default => no cap)

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `FP_DB_PATH` | `fingerprints.db` | SQLite database file path |
| `ADMIN_API_KEY` | *(required for inserts/deletes)* | API key for `/songs` insert and delete |
| `MAX_SONGS` | *(unset = no limit)* | Max number of songs allowed in DB |

## Running the Backend (Local)

You must set environment variables before starting the server. See the examples below.

**macOS/Linux**
```bash
cd backend/app
ADMIN_API_KEY=supersecret python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

**Windows PowerShell**
```powershell
cd backend/app
$env:ADMIN_API_KEY="supersecret"
python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

**Windows CMD**
```cmd
cd backend/app
set ADMIN_API_KEY=supersecret && python -m uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

### Insert a Song

Some curl examples shown below. Once the server is running, you can insert songs with:

```bash
curl -F "file=@/path/to/song.wav" -H "X-API-Key: supersecret" "http://127.0.0.1:8000/songs"
```

### Identify a Sample

```bash
curl -F "file=@/path/to/sample.wav" "http://127.0.0.1:8000/identify"
```

Example response:
```json
{"match":{"song_name":"Example artist - Example song","timestamp_seconds":64,"certainty":99}}
```
Certainty is reported as a percentage confidence score. Higher values indicate a more reliable match.

### List Songs

```bash
curl "http://127.0.0.1:8000/songs"
```

### Delete a Song

```bash
curl -X DELETE -H "X-API-Key: supersecret" "http://127.0.0.1:8000/songs/123"
```

## Running the Backend with Docker

Build:

```bash
docker build -t audio-fp-backend backend
```

Run:

You should set `ADMIN_API_KEY`. You can also set `FP_DB_PATH`, optionally set `MAX_SONGS`, and mount a volume to persist the database.

```bash
docker run -p 8000:8000 -e ADMIN_API_KEY=supersecret -e FP_DB_PATH=/data/fingerprints.db -e MAX_SONGS=100 -v /srv/audio-fp/data:/data audio-fp-backend
```

On Windows, use a Windows path for the volume:

```bash
docker run -p 8000:8000 -e ADMIN_API_KEY=supersecret -e FP_DB_PATH=/data/fingerprints.db -v C:\audio-fp-data:/data audio-fp-backend
```

## Frontend (Static Web)

The frontend records audio, sends it to `/identify`, and displays the match result. It also lists available songs from `/songs`.

### Configure API URL

Edit `docs/config.js` to point to your backend API (or `http://localhost:8000` for local dev):

```js
window.API_BASE = "https://YOUR_BACKEND_URL_HERE";
```

This file is committed so the demo works out of the box. Change it to your own backend URL if you deploy separately.

### Run Locally
For example:
```bash
cd docs
python -m http.server 5173
```

Open:

```
http://127.0.0.1:5173/
```

## API Summary

- `POST /songs` (protected) - insert a song
- `GET /songs` - list available songs
- `DELETE /songs/{id}` (protected) - delete a song
- `POST /identify` - identify a sample

## Notes

- The database is SQLite.
- Fingerprints are generated from spectrogram peaks and stored with timestamps.
- Matching uses fingerprint hash collisions and time-offset voting.
