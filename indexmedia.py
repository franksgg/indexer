import base64
import binascii
import os
import pathlib
import re
import sys
import traceback
from configparser import ConfigParser

from io import BytesIO
from typing import Optional

import discogs_client
import mediafile
import requests
from PIL import Image
from discogs_client.models import MixedPaginatedList
from requests.adapters import HTTPAdapter
from urllib3.response import HTTPResponse

import connector
from tools import normalize_name


class FileAdapter(HTTPAdapter):
    def send(self, request, *args, **kwargs):
        resp = HTTPResponse(body=open(request.url[7:], "rb"), status=200, preload_content=False)
        return self.build_response(request, resp)


def toSigned32(n):
    n = n & 0xffffffff
    return n | (-(n & 0x80000000))


def fbcrc32(blob):
    return toSigned32(int(binascii.hexlify(bytearray.fromhex(binascii.crc32(blob).to_bytes(4, "big").hex())[::-1]), 16))


class Indexer(object):
    class MyAlbum(object):
        ID: Optional[int] = None
        NAME: Optional[str] = None
        PYEAR: Optional[str] = None
        FK_IMAGE: Optional[str] = None
        ARTIST: Optional[str] = None
        TIDID: Optional[str] = None

    class MyArtist(object):
        ID: Optional[int] = None
        NAME: Optional[str] = None
        EVENTS: Optional[str] = None
        FK_IMAGE: Optional[str] = None
        TIDID: Optional[str] = None

    class MyTrack(object):
        ID: Optional[int] = None
        PATH: Optional[str] = None
        TITLE: Optional[str] = None
        BITRATE: Optional[str] = None
        FILE_SIZE: Optional[str] = None
        LEN: Optional[float] = None
        NUMBER: Optional[str] = None
        ALBUM_PK: Optional[str] = None
        ARTIST_PK: Optional[str] = None
        LYRICS_PK: Optional[str] = None
        PYEAR: Optional[str] = None
        VOTES: Optional[int] = None
        SAMPLERATE: Optional[int] = None
        FK_IMAGE: Optional[str] = None
        TIDID: Optional[str] = None

    class discogsinfo(object):
        track = None
        artist = None
        album = None
        albumimage = None
        artistimage = None

    def __init__(self):
        """Initialize the Indexer with configuration and connections."""
        # Initialize internal state
        self.logfile = open('indexer.log', 'a')
        print("Starting indexer", file=self.logfile)
        self.session = requests.Session()
        self.discogsinfo = self.discogsinfo()
        self.session.mount("file://", FileAdapter())
        self.fullscan = False
        self.clean = False
        self.start = None
        self.startpath = ""
        self.file_path = ""
        self.formats = ("flac", "mp3", "m4a")
        self.id3r = None
        self.artists = {}
        self.albums = {}
        self.media_dirs = ()
        self.mybase = ""
        self.albuminfo = None
        self.con = None
        self.discogsclient = None

        self._artist_cache = {}
        self._album_cache = {}
        self._discogs_cache = {}
        self._cur = None

        # Load configuration
        config = ConfigParser()
        config_files = ["/etc/iceshake/iceshake.ini", "iceshake.ini", "../iceshake.ini"]
        found_files = config.read(config_files)
        if not found_files:
            print(f"Warning: None of the config files {config_files} were found.", file=self.logfile)

        try:
            # Set up database connections
            print("Connecting to database", file=self.logfile)
            connection = connector.Connector()
            self.con = connection.getconnection()
            self._cur = self.con.cursor()
            discogs_key = config.get("Indexer", "discogs")

            self.discogsclient = discogs_client.Client('indexmedia/0.1', user_token=discogs_key)

            formats_value = config.get("Indexer", "formats")
            self.formats = tuple(
                fmt.strip().lower().lstrip(".")
                for fmt in formats_value.split(",")
                if fmt.strip()
            ) or self.formats

            # Get media directories
            self.mybase = os.path.normpath(config.get("Indexer", "basedir"))
            mypath = os.path.join(self.mybase, os.path.normpath(config.get("Indexer", "dir")))
            startpath = os.path.normpath(config.get("Indexer", "startdir"))
            if startpath == ".":
                self.startpath = mypath
            else:
                self.startpath = os.path.join(mypath, startpath)
            self.media_dirs = (mypath,)
            # Get other configuration options
            self.fullscan = config.getboolean("Indexer", "fullscan")
            self.clean = config.getboolean("Indexer", "cleanup")

            # Validate configuration
            if len(self.media_dirs) == 0:
                print("Remember to set the MEDIA_DIRS option, otherwise I don't know where to look for.", file=self.logfile)

        except Exception as e:
            print(f"Error during initialization: {e}", file=self.logfile)
            if not self.media_dirs:
                self.media_dirs = ()
            if not self.startpath:
                self.startpath = ""

    # ... existing code ...

    def fill_discogs(self, tinfo):
        self.discogsinfo.album = None
        self.discogsinfo.albumimage = None
        self.discogsinfo.artist = None
        self.discogsinfo.artistimage = None

        track_artist = getattr(tinfo, "artist", None)
        track_album = getattr(tinfo, "album", None)
        track_title = getattr(tinfo, "title", None)
        album_artist = getattr(tinfo, "albumartist", None)

        if track_artist and track_album:
            cache_key = (track_artist, track_album)
            if cache_key in self._discogs_cache:
                cached = self._discogs_cache[cache_key]
                if cached:
                    self.discogsinfo.album = cached['album']
                    self.discogsinfo.albumimage = cached['albumimage']
                    self.discogsinfo.artist = cached['artist']
                    self.discogsinfo.artistimage = cached['artistimage']
                return None
        else:
            cache_key = (track_artist, track_title)

        artist = album_artist or track_artist
        if not artist or not track_title or self.discogsclient is None:
            self._discogs_cache[cache_key] = None
            return None

        results = self.search_discogs(artist, tinfo)
        if results is not None:
            p = results.page(1)
            for release in p:
                try:
                    if release.images:
                        self.discogsinfo.album = release
                        self.discogsinfo.albumimage = release.images[0]['uri']
                        self.discogsinfo.artist = release.artists
                        for release_artist in self.discogsinfo.artist:
                            if release_artist.images:
                                self.discogsinfo.artistimage = release_artist.images[0]['uri']
                                self._discogs_cache[cache_key] = {
                                    'album': self.discogsinfo.album,
                                    'albumimage': self.discogsinfo.albumimage,
                                    'artist': self.discogsinfo.artist,
                                    'artistimage': self.discogsinfo.artistimage,
                                }
                                return None
                except Exception as e:
                    print(f"Error getting discogs info: {e}", file=self.logfile)
        self._discogs_cache[cache_key] = None
        return None

    def search_discogs(self, artist, tinfo) -> Optional[MixedPaginatedList]:
        if self.discogsclient is None:
            return None

        album = getattr(tinfo, "album", None)
        title = getattr(tinfo, "title", None)
        year = getattr(tinfo, "year", None)

        if not artist or not title:
            return None

        if not album:
            results = self.discogsclient.search(
                artist=normalize_name(artist),
                track=normalize_name(title, True),
                type='release'
            )
        else:
            results = self.discogsclient.search(
                artist=normalize_name(artist),
                track=normalize_name(title, True),
                title=normalize_name(album, True),
                type='release'
            )
            if results.count == 0:
                results = self.discogsclient.search(
                    artist=normalize_name(artist),
                    title=normalize_name(album),
                    type='release'
                )
            if results.count == 0 and year:
                results = self.discogsclient.search(
                    artist=normalize_name(artist),
                    title=normalize_name(album, True),
                    year=year,
                    type='release'
                )
                if results.count == 0:
                    results = self.discogsclient.search(
                        track=normalize_name(title, True),
                        year=year,
                        artist=normalize_name(artist),
                        type='release'
                    )

        return results if results.count > 0 else None

    def is_track(self):
        """Tries to guess whether the file is a valid track or not.
        """
        if os.path.isdir(self.file_path):
            return False

        if "." not in self.file_path:
            return False

        ext = self.file_path[self.file_path.rfind(".") + 1:]
        # print(ext, self.formats)
        if ext not in self.formats:
            return False

        return True

    def walk(self, dir_name, albuminfo):
        """Recursively walks through a directory looking for tracks.
        """

        if os.path.isdir(dir_name):
            if dir_name == self.startpath:
                self.start = True
            for name in sorted(os.listdir(dir_name)):
                # sys.stdout.write('.')
                # sys.stdout.flush()
                ignore = os.path.join(dir_name, ".ignore")
                self.file_path = os.path.join(dir_name, name)
                if self.file_path == self.startpath:
                    self.start = True
                if self.file_path == ignore:
                    sys.stdout.write("ignored: " + dir_name + "\n")
                    sys.stdout.flush()
                    break
                if self.start and os.path.isdir(self.file_path):
                    newalbuminfo = pathlib.Path(os.path.join(self.file_path, "AlbumInfo.txt"))
                    if newalbuminfo.exists():
                        albuminfo = newalbuminfo
                    if albuminfo is None:
                        albuminfo = pathlib.Path(os.path.join(self.file_path, "AlbumInfo.txt"))
                        if not albuminfo.exists():
                            albuminfo = None
                    self.walk(self.file_path, albuminfo)
                else:
                    if self.start and self.is_track():
                        # sys.stdout.write(self.file_path + "\n")
                        # sys.stdout.flush()

                        self.save_track(albuminfo)
        else:
            self.file_path = dir_name
            if self.is_track():
                self.save_track(albuminfo)

        return True

    def cleanup(self):

        def check_ignore(fname):

            aktdir = os.path.dirname(fname)

            while aktdir != self.mybase:
                ignorepath = os.path.join(aktdir, '.ignore')
                if os.path.exists(ignorepath):
                    return True
                aktdir = os.path.split(aktdir)[0]

            return False

        def delentry(fname, row_id):
            print('deleting ', row_id, fname, file=self.logfile)
            delstmt = 'delete from tracks where id=%s' % (row_id)
            self._cur.execute(delstmt)

        self._cur.execute('select ID,PATH from tracks')
        print('Checking ', file=self.logfile)
        c = 0

        tracks_to_check = self._cur.fetchall()
        for row in tracks_to_check:
            filename = row[1]
            row_id = row[0]

            if not os.path.exists(filename) or check_ignore(filename):
                delentry(filename, row_id)
            else:
                c = c + 1

        self.con.commit()
        print(c, file=self.logfile)
        print('ok', file=self.logfile)

    def run(self):
        """Main method to index media files and optionally retrieve missing images."""
        try:
            if self.clean:
                self.cleanup()
            # Process all media directories
            for mdir in self.media_dirs:
                if not os.path.exists(mdir):
                    print(f"Warning: Media directory {mdir} does not exist", file=self.logfile)
                    continue
                print(f"Processing directory: {mdir}",file=self.logfile)
                self.walk(mdir, None)

            print("Indexing completed successfully",file=self.logfile)
            self.con.commit()
            self.con.close()
            print("Database connection closed",file=self.logfile)
        except Exception as e:
            print(f"Error during indexing: {e}",file=self.logfile)

    def parsealbuminfo(self, albuminfo_path):
        """
        Read album information from the given file and store it in a dictionary.

        Args:
            albuminfo_path (pathlib.Path): Path to the AlbumInfo.txt file

        Returns:
            dict: Dictionary containing the album information
        """
        album_info = {}
        current_cd = None
        tracks = {}

        try:
            with open(albuminfo_path, 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()

                    # Skip empty lines
                    if not line:
                        continue

                    # Check for CD section headers
                    if line.startswith('===========CD '):
                        cd_match = re.search(r'CD (\d+)', line)
                        if cd_match:
                            current_cd = int(cd_match.group(1))
                            tracks[current_cd] = {}
                        continue

                    # Check for track listings
                    track_match = re.match(r'\[(\d+)]\s+(.*)', line)
                    if track_match and current_cd is not None:
                        track_num = int(track_match.group(1))
                        track_title = track_match.group(2).strip()
                        tracks[current_cd][track_num] = track_title
                        continue

                    # Check for album metadata
                    meta_match = re.match(r'\[(.*?)]\s+(.*)', line)
                    if meta_match:
                        key = meta_match.group(1)
                        value = meta_match.group(2).strip()

                        # Convert numeric values
                        if key in ['ID', 'SongNum', 'Duration']:
                            try:
                                value = int(value)
                            except ValueError:
                                pass  # Keep as string if conversion fails

                        album_info[key] = value

            # Add tracks to album_info
            if tracks:
                album_info['Tracks'] = tracks

            return album_info

        except Exception as e:
            print(f"Error parsing album info file {albuminfo_path}: {e}",file=self.logfile)
            print(traceback.format_exc(),file=self.logfile)
            print(f"Album info: {album_info}",file=self.logfile)
            return {}

    def writealbuminfo(self, album_info, albuminfo_path):
        """
        Write album information to the given file.

        Args:
            album_info (dict): Dictionary containing the album information
            albuminfo_path (pathlib.Path): Path to the AlbumInfo.txt file

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(albuminfo_path, 'w', encoding='utf-8') as file:
                # Write album metadata first (all keys except 'Tracks')
                for key, value in album_info.items():
                    if key != 'Tracks':
                        file.write(f"[{key}]{' ' * (12 - len(key))}{value}\n")

                # Add a blank line after metadata
                file.write("\n")

                # Write track listings organized by CD
                if 'Tracks' in album_info:
                    for cd_num in sorted(album_info['Tracks'].keys()):
                        file.write(f"===========CD {cd_num}=============\n")
                        for track_num in sorted(album_info['Tracks'][cd_num].keys()):
                            track_title = album_info['Tracks'][cd_num][track_num]
                            file.write(f"[{track_num}]{' ' * (5 if track_num < 10 else 4)}{track_title}\n")

            return True

        except Exception as e:
            print(f"Error writing album info file {albuminfo_path}: {e}",file=self.logfile)
            print(traceback.format_exc(),file=self.logfile)
            return False

    def save_track(self, albuminfo):
        """
        Save track information to the database.

        Args:
            albuminfo: Path to the AlbumInfo.txt file, or None if not available
        """
        full_path = self.file_path
        print(full_path,file=self.logfile)
        self.logfile.flush()

        if not self.fullscan and self.track_already_there(full_path):
            print("Already there, skipping: ", file=self.logfile)
            return
        else:
            print("Analyzing track : ", file=self.logfile)

        try:
            tinfo = mediafile.MediaFile(full_path)
        except Exception as e:
            print(f"Error reading media file {full_path}: {e}", file=self.logfile)
            return

        self.fill_discogs(tinfo)
        artist = self.MyArtist()
        self.fillartist(artist, tinfo)
        album = self.MyAlbum()
        self.fillalbum(album, tinfo, artist)
        track = self.MyTrack()
        self.filltrack(track, tinfo)
        self.get_track_image(track, tinfo.images)
        # print("Artist: " + actartist + ';')
        # print(tinfo.length)

        # No Tidal track ID available; keep default TIDID (None or 0)
        self.get_album_image(album, artist.NAME, track)
        self.get_artist_image(artist)

        self.save_artist(track, artist)
        self.save_album(track, album)
        inst = ("update or insert into TRACKS (PATH, TITLE,  BITRATE, samplerate, FILE_SIZE, LEN, NUMBER, PYEAR, "
                "ARTIST_PK,ALBUM_PK, TIDID,IMAGE_PK)  values (?,?,?,?,?,?,?,?,?,?,?,?) matching (PATH)")
        self._cur.execute(inst, (full_path, track.TITLE, track.BITRATE, track.SAMPLERATE, track.FILE_SIZE,
                                 int(round(float(track.LEN))), track.NUMBER, track.PYEAR, track.ARTIST_PK,
                                 track.ALBUM_PK, track.TIDID, track.FK_IMAGE))
        self.con.commit()
        print(f" Artist: {artist.NAME}  Title: {track.TITLE} Album: {album.NAME}",file=self.logfile)
        print(f" ArtistImg-ID: {artist.FK_IMAGE} AlbumImg-ID {album.FK_IMAGE}",file=self.logfile)
        print("----------------",file=self.logfile)
        return True

    def filltrack(self, track, tinfo):

        track.TITLE = normalize_name(tinfo.title[:128], True)
        track.BITRATE = tinfo.bitrate
        track.FILE_SIZE = tinfo.filesize
        track.LEN = tinfo.length
        track.PYEAR = tinfo.year
        track.SAMPLERATE = tinfo.samplerate
        track.BITRATE = tinfo.bitrate
        track.TIDID = 0

    def fillalbum(self, album, tinfo, artist=None):

        album.PYEAR = tinfo.year
        album.ARTIST = tinfo.artist
        if album.ARTIST is None:
            album.ARTIST = tinfo.albumartist

        try:
            if self.discogsinfo.album:
                album.NAME = self.discogsinfo.album.title
            album.ARTIST = artist.NAME
        except AttributeError:
            album.NAME = None

        if album.NAME is None:
            album.NAME = tinfo.album
        if album.NAME is None:
            album.NAME = 'unknown'
        if album.PYEAR is None:
            album.PYEAR = tinfo.year
        album.NAME = normalize_name(album.NAME)
        album.ARTIST = normalize_name(album.ARTIST)

        cache_key = (album.NAME, album.ARTIST)
        if cache_key in self._album_cache:
            album.ID = self._album_cache[cache_key]
        else:
            self._cur.execute('select first(1) a.id from albums a where a.name=? and a.artist=?',
                              (album.NAME, album.ARTIST,))
            try:
                album.ID = int(self._cur.fetchone()[0])
                self._album_cache[cache_key] = album.ID
            except:
                album.ID = None

        album.TIDID = None

    def fillartist(self, artist, tinfo):
        try:
            if self.discogsinfo.artist:
                artist.NAME = self.discogsinfo.artist[0].name
        except AttributeError:
            artist.NAME = None
        # Tidal artist lookup removed
        if artist.NAME is None:
            artist.NAME = tinfo.artist

        if artist.NAME is None:
            artist.NAME = tinfo.albumartist
        if artist.NAME is None:
            artist.NAME = 'unknown'
        artist.NAME = normalize_name(artist.NAME)

        if artist.NAME in self._artist_cache:
            artist.ID = self._artist_cache[artist.NAME]
        else:
            self._cur.execute('select first(1) a.id from artists a where a.name=?', (artist.NAME,))
            try:
                artist.ID = self._cur.fetchone()[0]
                self._artist_cache[artist.NAME] = artist.ID
            except:
                artist.ID = None
        artist.TIDID = None

    def get_album_image(self, album, artistname, track):
        clink = None
        if track is not None:
            if track.FK_IMAGE is not None:
                album.FK_IMAGE = track.FK_IMAGE
                return album.FK_IMAGE
        if album.ID is not None:
            album.FK_IMAGE = self.GetALbumImageById(album.ID)
            if album.FK_IMAGE:
                return album.FK_IMAGE

        clink = self.discogsinfo.albumimage

        if clink:
            album.FK_IMAGE = self.save_new_image(clink, artistname, album.NAME, album.TIDID)
            return album.FK_IMAGE

    def get_artist_image(self, artist):
        unknown = 'https://resources.tidal.com/images/1e01cdb6/f15d/4d8b/8440/a047976c1cac/320x320.jpg'
        if artist.ID is not None:
            artist.FK_IMAGE = self.GetArtistImageById(artist.ID)
            if artist.FK_IMAGE:
                return artist.FK_IMAGE
        # Tidal artist lookup removed; try Spotify fallback
        clink = self.discogsinfo.artistimage

        if clink and not clink == unknown:
            artist.FK_IMAGE = self.save_new_image(clink, artist.NAME, None, None)
            return artist.FK_IMAGE

    def GetImageId(self, artistimg):
        rhash = fbcrc32(artistimg)
        insi = ('select i.id from images i where i.crc32=?')
        self._cur.execute(insi, (rhash,))
        d = self._cur.fetchone()
        if d:
            return d[0]
        else:
            return None

    def get_track_image(self, track, images):
        image = None
        try:
            for image in images:
                print(image.mime_type, file=self.logfile)
                break
        except:
            image = None
        img = None
        if image:
            # print(image)
            try:
                img = Image.open(BytesIO(image.data))
            except:
                try:
                    img = Image.open(BytesIO(base64.standard_b64decode(image.data)))
                except:
                    return None
            # print('adding %s image for pk %s' % (img.format, pkt))
            basewidth = 300
            width = img.size[0]
            if width != basewidth:
                # height = img.size[1]
                wpercent = (basewidth / float(img.size[0]))
                hsize = int((float(img.size[1]) * float(wpercent)))
                img = img.resize((basewidth, hsize), Image.Resampling.LANCZOS)
            image2 = BytesIO()
            img.save(image2, "PNG")
            track.FK_IMAGE = self.saveimage(self.file_path, image2)

    def saveimage(self, fpath, image2, mimetype=None):
        id = self.GetImageId(image2.getvalue())
        if id:
            return id
        inst = 'insert into images (image,source,mimetype) values(?,?,?) returning id'
        if not mimetype:
            mimetype = 'image/png'
        self._cur.execute(inst, (image2.getvalue(), fpath, mimetype))
        d = self._cur.fetchone()
        self.con.commit()
        return d[0]

    def save_artist(self, track, artist):
        insa = "update or insert into ARTISTS (NAME, FK_IMAGE, TIDID) values (?,?,?) matching (NAME) returning id"
        self._cur.execute(insa, (artist.NAME, artist.FK_IMAGE, artist.TIDID))
        d = self._cur.fetchone()
        if track:
            # track.FK_IMAGE = self.GetImageId(artist.TIDID)
            track.ARTIST_PK = d[0]
        self.con.commit()

    def save_album(self, track, album):
        insl = ("update or insert into ALBUMS (NAME, artist, PYEAR, FK_IMAGE,TIDID) values (?, ?, ?, ?,?) matching ("
                "NAME,artist) returning id")
        self._cur.execute(insl, (album.NAME[:128], album.ARTIST, album.PYEAR, album.FK_IMAGE, album.TIDID))
        d = self._cur.fetchone()
        if track:
            track.ALBUM_PK = d[0]
        self.con.commit()

    def track_already_there(self, full_path):
        self._cur.execute('select first(1) t.tidid from tracks t where t.path=?', (full_path,))
        res = self._cur.fetchone()
        if res:
            return True
        else:
            return False

    def GetArtistImageById(self, ID):
        self._cur.execute('select first(1) a.fk_image from artists a where a.id=?', (ID,))
        res = self._cur.fetchone()
        if res:
            return res[0]
        else:
            return None

    def GetALbumImageById(self, ID):
        self._cur.execute('select first(1) a.fk_image from albums a where a.id=?', (ID,))
        res = self._cur.fetchone()
        if res:
            return res[0]
        else:
            return None

    def save_new_image(self, clink, artistname, albumname, tidid):
        user_agent = {'User-agent': 'Mozilla/5.0'}
        albumlink = self.session.get(clink, headers=user_agent)
        albumimg = albumlink.content
        albummime = albumlink.headers['content-type']
        fk_image = self.GetImageId(albumimg)
        if fk_image is None:
            rhash = fbcrc32(albumimg)

            insi = (
                'update or insert into images (image,source,mimetype,hint,tidid,crc32) values(?,?,?,?,?,?) matching (crc32) '
                'returning id')
            if artistname:
                hint = artistname
            else:
                hint = ''
            if albumname:
                hint = hint + ': ' + albumname
            self._cur.execute(insi, (albumimg, clink, albummime, hint, tidid, rhash,))
            d = self._cur.fetchone()
            fk_image = d[0]
            self.con.commit()
        return fk_image


if __name__ == '__main__':
    lola = Indexer()
    # print(sys.argv[1])
    # print(lola.get_discogs_image('ZZ Top'))
    # print(p)
    lola.logfile.flush()
    lola.run()
