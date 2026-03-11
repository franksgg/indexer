# IndexMedia

IndexMedia is a Python-based music library indexer that scans your music collection and stores metadata in a Firebird database. It features automatic metadata enrichment using the Discogs API and includes support for multiple audio formats.
It is based on an early version of the indexer of the shiva project. (https://github.com/tooxie/shiva-server)

## Features

- **Recursive Scanning**: Scans music directories and subdirectories for audio files.
- **Multi-format Support**: Indexes FLAC, MP3, and M4A files (extensible).
- **Metadata Extraction**: Extracts tags using `mediafile`.
- **Discogs Integration**: Automatically fetches artist and album information, including cover art, from Discogs.
- **Database Storage**: Stores all metadata (tracks, albums, artists, images) in a Firebird database.
- **Intelligent Normalization**: Cleans up track and album titles (removes common prefixes and suffixes like "20th Anniversary Edition").
- **Docker Support**: Includes a Dockerized setup for both the Firebird database and the Python indexer.

## Prerequisites

- **Python 3.x**
- **Firebird SQL Server** (v3.0 or later recommended)
- **Discogs API Token** (for metadata enrichment)

### Python Dependencies

Install the required packages using pip:

```bash
pip install -r requirements.txt
```

Key dependencies include:
- `fdb`: Firebird database driver
- `discogs-client`: For Discogs API access
- `mediafile`: For reading audio tags
- `Pillow`: For image processing
- `requests`: For HTTP requests

## Configuration

The indexer is configured via `iceshake.ini`. A template `iceshake.ini.dist` is provided.

### Database Connection (`[Connection]`)

| Parameter | Description |
|-----------|-------------|
| `host` | Firebird server host (e.g., `localhost` or `fb` in Docker) |
| `database` | Path to the Firebird database file (.fdb) |
| `user` | Database username |
| `password` | Database password |
| `fb_library_name` | Path to the Firebird client library (`libfbclient.so` on Linux) |

### Indexer Settings (`[Indexer]`)

| Parameter | Description |
|-----------|-------------|
| `basedir` | Root directory of your music library |
| `dir` | Specific subdirectory under `basedir` to scan |
| `startdir` | Subdirectory of `dir` to start scanning from (use `.` for all) |
| `discogs` | Your Discogs API token |
| `formats` | Comma-separated list of extensions to index (e.g., `flac,mp3,m4a`) |
| `fullscan` | `True` to rescan all files, `False` to only add new ones |
| `cleanup` | `True` to remove entries from the database that no longer exist on disk |

## Usage

### Running Locally

1. Ensure your Firebird database is running and the schema is initialized.
2. Configure `iceshake.ini`.
3. Run the indexer:

```bash
python indexmedia.py
```

### Running with Docker

The project includes a `docker-compose.yaml` in the `docker/` directory for a full environment.

1. Navigate to the `docker` directory:
   ```bash
   cd docker
   ```
2. Start the services:
   ```bash
   docker compose up -d
   ```

This will start:
- A `firebird` service with the database.
- A `python` service that runs the `indexmedia.py` script.

Make sure to mount your music directory correctly in `docker/compose.yaml` (default is `/var/data/music/`).

## Project Structure

- `indexmedia.py`: Main entry point and indexing logic.
- `connector.py`: Database connection management.
- `tools.py`: Utility functions for normalization and time conversion.
- `iceshake.ini`: Configuration file (local/custom).
- `docker/`: Docker configuration, SQL DDL, and initialization scripts.
- `requirements.txt`: Python package requirements.

## Internal Details

- **AlbumInfo.txt**: If found in a directory, the indexer can parse this file for custom album metadata.
- **.ignore**: Placing a `.ignore` file in a directory will cause the indexer to skip that directory and its subdirectories.
- **Image Caching**: Cover art and artist images are cached in the database to avoid redundant API calls.

## License

See the `LICENSE` file for details.
