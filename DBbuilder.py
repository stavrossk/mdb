#!/usr/bin/python

import urllib2
import simplejson
import os
from subprocess import call
import sys
import sqlite3
import wx_signal
import wx
import re
import threading

api_url = 'http://www.imdbapi.com/?t='
out_dir = '.mdb'
movie_formats = ['avi', 'mkv', 'mp4']
#http_proxy = 'proxy22.iitd.ac.in:3128'
#https_proxy = 'proxy22.iitd.ac.in:3128'
http_proxy = None
https_proxy = None
img_size = '100'


def zenity_error(msg):
    call(['zenity', '--error', '--text', msg])


def setup(conn=None, cursor=None):
    print "running setup"
    os.mkdir(out_dir)
    os.mkdir(os.path.join(out_dir, 'images'))
    create_database(conn, cursor)


def create_database(conn=None, cursor=None):
    if conn is None:
        conn = sqlite3.connect(os.path.join(out_dir, 'mdbdata.sqlite'))
        cursor = conn.cursor()

    cursor.execute('''CREATE TABLE movies (
            filename TEXT,
            title TEXT,
            year INTEGER,
            released TEXT,
            genre TEXT,
            rating REAL,
            runtime TEXT,
            director TEXT,
            actors TEXT,
            plot TEXT,
            poster TEXT
            )''')
    cursor.execute('CREATE UNIQUE INDEX filename_index ON movies (filename)')
    conn.commit()


def add_to_db(filename, file_data, conn, cursor):
    cursor.execute('INSERT INTO movies VALUES(?,?,?,?,?,?,?,?,?,?,?)', (filename,
        file_data['Title'], file_data['Year'], file_data['Released'],
        file_data['Genre'], file_data['imdbRating'], file_data['Runtime'],
        file_data['Director'], file_data['Actors'], file_data['Plot'],
        file_data['Poster']))
    conn.commit()


def get_movie_name(filename):
    # 1. Find a year, reject everything after it, clean up
    # 2. Find a reject word(like Dvd, brrip, xvid), reject everything
    # after it, clean up
    # 3. Split by some token, try to remove the last words and do a
    # search #NOT_IMPLEMENTED
    reject_words = ['dvd', 'xvid', 'brrip', 'r5', 'unrated', '720p',
            'x264', 'klaxxon', 'axxo', 'sample', 'br_300', '300mb']
    reject_words_strict = ['eng', 'scr', 'dual']  # UNUSED
    #prepare: remove ext, make lower
    if (filename[-4] == '.'):
        filename = filename[:-4]

    filename = filename.lower()

    #1
    year_split = re.split('\d\d\d\d', filename)
    if (len(year_split) > 1):
        filename = year_split[0]

    #2
    for word in reject_words:
        if (filename.find(word) != -1):
            filename = filename[:filename.find(word)]

    #cleanup
    filename = re.sub('\s+', ' ',
            re.sub('[\._\-\[\(\]\)]', ' ', filename).strip())

    return filename


def get_imdb_data(moviename):
    res = simplejson.load(urllib2.urlopen(api_url +
        urllib2.quote(moviename)))
    if (res['Response'] == 'True'):
        return res
    else:
        return None


def process_file(dbthread, filename, conn, cursor):
    file_data = get_imdb_data(get_movie_name(filename))
    for item in file_data:
        if file_data[item] == 'N/A':
            file_data[item] = None

    if (file_data is not None):
        # Add to db, save img, send signal
        add_to_db(filename, file_data, conn, cursor)
        if file_data['Poster'] is not None:
            # save image
            img_url = file_data['Poster'][:-7] + img_size + '.jpg'
            img_file = os.path.join(out_dir, 'images', filename + '.jpg')
            img_fh = open(img_file, 'wb')
            img_fh.write(urllib2.urlopen(img_url).read())
            img_fh.close()
        dbthread.signal_gui(filename)


def process_files(dbthread, files, directory):
    # set proxies
    if (http_proxy is not None):
        os.environ['http_proxy'] = http_proxy
    if (https_proxy is not None):
        os.environ['https_proxy'] = https_proxy

    os.chdir(directory)

    if (not os.path.exists(out_dir)):
        setup()

    conn = sqlite3.connect(os.path.join(out_dir, 'mdbdata.sqlite'))
    cursor = conn.cursor()

    try:
        for filename in files:
            process_file(dbthread, filename, conn, cursor)
    except Exception, e:
        zenity_error(str(e))
        raise


class DBbuilderThread(threading.Thread):
    def __init__(self, parent, files, directory):
        threading.Thread.__init__(self)
        self.parent = parent
        self.files = files
        self.directory = directory

    def run(self):
        """Overrides Thread.run. Don't call this directly its called internally
        when you call Thread.start().
        """
        process_files(self, self.files, self.directory)

    def signal_gui(self, filename):
        evt = wx_signal.FileDoneEvent(wx_signal.myEVT_FILE_DONE, -1, filename)
        wx.PostEvent(self.parent, evt)