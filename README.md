# Audio Fingerprinting Service

This project implements an audio fingerprinting and matching service inspired by techniques used in systems like Shazam. It includes a FastAPI backend for inserting and identifying songs, and a lightweight frontend for recording audio and testing matches.

## Repository Layout

- `backend/` - FastAPI service, fingerprinting logic, and SQLite storage
- `client/web/` - Static frontend (HTML/CSS/JS) for recording and identification

## Backend Overview

The backend:

- extracts fingerprints from audio
- stores song metadata and fingerprints in SQLite
- matches a short sample against stored fingerprints

### Key Limits

- Inserted songs must be **1-5 minutes** long
- Identify samples must be **≤ 15 seconds**
- Maximum number of songs is capped (default **100**)

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
{"match":{"song_name":"epic","timestamp_seconds":64.88462585034014,"certainty":99}}
```

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

Edit `client/web/config.js` to point to your backend API:

```js
window.API_BASE = "https://YOUR_BACKEND_URL_HERE";
```

This file is committed so the demo works out of the box. Change it to your own backend URL if you deploy separately.

### Run Locally

```bash
cd client/web
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
