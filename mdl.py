#!/usr/bin/env python3

import sys, re, csv, base64, hashlib
import yt_dlp
import music_tag

DLIST_COLUNMS = ['artist', 'title', 'album', 'track_number', 'url']

def is_url(url):
    return bool(re.search(r'^https?:\/\/.+\.', url))

def url_info(url):
    ydl_opts = {'extract_flat': 'in_playlist',
                'quiet': True,
                'retries': 4,
                'simulate': True,
                'skip_download': True}
    def extract_entry_url(entry):
        return entry.get('webpage_url', entry.get('url', None))
    print(f"downloading info from {url}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url)
        except yt_dlp.utils.DownloadError:
            return {'type': 'error'}
        if info.get('_type', None) == 'playlist':
            assert('entries' in info.keys())
            assert(len(info['entries']) > 0)
            entry_urls = [extract_entry_url(entry) for entry in info['entries']]
            return {'type': 'playlist', 'urls': entry_urls}
        else:
            tinfo = {'type': 'track'}
            tinfo['url'] = extract_entry_url(info)
            tinfo['title'] = info.get('track', info.get('title', None))
            tinfo['artist'] = info.get('channel', info.get('uploader', None))
            tinfo['thumbnail'] = info.get('thumbnail', None)
            assert(tinfo['url'] != None)
            return tinfo

def parse_catalogue(catalogue_file, old_dlist):
    dlist_cache = {dentry['url']:dentry for dentry in old_dlist}
    dlist = []
    title = ''
    artist = ''
    album = ''
    playlists = {}
    current_playlists = []
    track_number = 0
    line_number = 0

    def add_dentry(dentry):
        nonlocal track_number
        dlist.append(dentry)
        if track_number > 0: track_number += 1
        for p in current_playlists:
            playlists[p] = playlists.get(p, [])
            playlists[p].append(dentry)

    def add_url(url, expect_track=False):
        if cached_dentry := dlist_cache.get(url, None):
            dentry = {
                'url': url,
                'title': title if title != '' else cached_dentry['title'],
                'artist': artist if artist != '' else cached_dentry['artist'],
                'album': album if album != '' else cached_dentry['album'],
                'track_number': track_number,
            }
            add_dentry(dentry)
        elif (info := url_info(url))['type'] == 'track':
            dentry = {
                'url': info['url'],
                'title': title if title != '' else info['title'],
                'artist': artist if artist != '' else info.get('artist', ''),
                'album': album,
                'track_number': track_number,
            }
            add_dentry(dentry)
        elif info['type'] == 'playlist':
            for track_url in info['urls']:
                add_url(track_url, expect_track=True)
        else:
            print(f"WARNING: failed to download info for {url}")

    for line in catalogue_file:
        line = line.strip()
        line_number += 1
        if line == '':
            artist = ''
            album = ''
            track_number = 0
            current_playlists = []
        elif re.search(r'^#', line):
            pass
        elif r := re.search(r'^ALBUM (.+)$', line):
            album = r.group(1)
            track_number = 1
        elif r := re.search(r'^ARTIST (.+)$', line):
            artist = r.group(1)
        elif r := re.search(r'^PLAYLISTS (.+)$', line):
            current_playlists = [p.strip() for p in r.group(1).split(',')]
        elif is_url(line):
            add_url(line)
        else:
            print(f"INVALID SYNTAX line {line_number}", file=sys.stderr)
            exit(1)

    for playlist,tracks in playlists.items():
        fname = f"{playlist}.m3u"
        f = open(f"{playlist}.m3u", 'w')
        print(f"writing playlist file {fname}")
        for dentry in tracks:
            f.write(f"{infer_fname(dentry)}.opus\n")
        f.close()
    return dlist

def infer_fname(dentry):
    id = base64.b64encode(hashlib.md5(dentry['url'].encode()).digest()).decode()[:8]
    desired = f"{dentry['title']} [{id}]"
    return re.sub(r'[\0\/\\\<\>:\|\?\*"]', '', desired)[:1023]

def download_song(dentry):
    fname_body = infer_fname(dentry)
    # python3 cli_to_api.py -o test --embed-thumbnail -f bestaudio -x --quiet --audio-format opus
    ydl_opts = {'extract_flat': 'discard_in_playlist',
                'final_ext': 'opus',
                'format': 'bestaudio',
                'fragment_retries': 10,
                'ignoreerrors': 'only_download',
                'noprogress': True,
                'outtmpl': {'default': fname_body, 'pl_thumbnail': ''},
                'postprocessors': [{'key': 'FFmpegExtractAudio',
                                    'nopostoverwrites': False,
                                    'preferredcodec': 'opus',
                                    'preferredquality': '5'},
                                   {'already_have_thumbnail': False, 'key': 'EmbedThumbnail'},
                                   {'key': 'FFmpegConcat',
                                    'only_multi_video': True,
                                    'when': 'playlist'}],
                'quiet': True,
                'retries': 10,
                'writethumbnail': True}
    print(f"downloading \"{dentry['title']}\" from {dentry['url']}")
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        err = ydl.download(dentry['url'])
        if err:
            print(f"WARNING: failed to download {dentry['url']}")
        else:
            f = music_tag.load_file(f"{fname_body}.opus")
            f['artist'] = dentry['artist']
            f['album'] = dentry['album']
            f['tracknumber'] = dentry['track_number']
            f['tracktitle'] = dentry['title']
            f.save()
        return err

def download_list(dlist, archive_fname):
    try:
        archive = open(archive_fname, 'r')
        archive_urls = {line.strip() for line in archive}
        archive.close()
    except FileNotFoundError:
        archive_urls = set()
    archive = open(archive_fname, 'a')
    for dentry in dlist:
        if dentry['url'] in archive_urls: continue
        download_song(dentry)
        archive.write(dentry['url'] + '\n')
        archive.flush()
        archive_urls.add(dentry['url'])
    archive.close()

def write_dlist(fname, dlist):
    f = sys.stdout if fname == '-' else open(fname, 'w')
    writer = csv.writer(f)
    for dentry in dlist:
        writer.writerow([dentry[c] for c in DLIST_COLUNMS])
    if fname != '-': f.close()
def read_dlist(fname):
    try:
        f = sys.stdout if fname == '-' else open(fname, 'r')
        reader = csv.reader(f)
        dlist = [{c:row[i] for i,c in enumerate(DLIST_COLUNMS)} for row in reader]
        if fname != '-': f.close()
        return dlist
    except FileNotFoundError:
        return []

print("generating dlist from catalogue...")

force_info_fetch = False
old_dlist = [] if force_info_fetch else read_dlist('.dlist')

catalogue_file = open('catalogue', 'r')
dlist = parse_catalogue(catalogue_file, old_dlist)
catalogue_file.close()

write_dlist('.dlist', dlist)

print("downloading audio...")

download_list(dlist, '.archive')

print("DONE")
