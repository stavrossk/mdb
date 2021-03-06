#!/usr/bin/python

import sys
import wx
import wx.lib.agw.ultimatelistctrl as ULC
from wx.lib.mixins.listctrl import ColumnSorterMixin
import sqlite3
from DBbuilder import create_database, is_in_db, DBbuilderThread, get_from_db
import os
import wx_signal
import wx.html
from html_window import ClickableHtmlWindow
from dialogs import HtmlDialog, PrefsDialog
import config
from update import UpdateThread
from multiprocessing.pool import ThreadPool


#CLASSES#
class MyFrame(wx.Frame, ColumnSorterMixin):
    def __init__(self, parent, conn, cur):
        wx.Frame.__init__(self, parent, -1, "MDB")
        self.set_icon()
        self.conn = conn
        self.cur = cur
        self.db_thread = None
        self.upd_thread = None

        self.Bind(wx_signal.EVT_FILE_DONE, self.on_file_done)
        self.Bind(wx_signal.EVT_SHOW_MSG, self.on_show_msg)
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.add_menu()
        self.add_sb()
        self.total_rows = 0

        self.sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(self.sizer)

        self.display_width = wx.GetDisplaySize()[0]
        self.itemDataMap = {}

        self.lst = self.build_list()
        ColumnSorterMixin.__init__(self, 6)
        self.sizer.Add(self.lst, 1, wx.EXPAND)
        self.Layout()

    def set_icon(self):
        ib = wx.IconBundle()
        ib.AddIconFromFile(config.get_resource('images', 'MDB_all.ico'),
            wx.BITMAP_TYPE_ICO)
        self.SetIcons(ib)
 
    def on_close(self, evt):
        if (self.db_thread is not None):
            self.db_thread.exit_now.set()
            self.db_thread.gui_ready.set()
            self.db_thread.join()
        if (self.upd_thread is not None):
            self.upd_thread.join()
        self.Destroy()

    def add_sb(self):
        sb = wx.StatusBar(self)
        self.sb = sb
        sb.SetFieldsCount(2)
        sb.SetStatusWidths([-2, -1])
        sb.SetStatusText("0 Files", 1)
        self.SetStatusBar(sb)

    def build_list(self):
        lst = ULC.UltimateListCtrl(
            self, wx.ID_ANY, agwStyle=wx.LC_REPORT | wx.LC_VRULES |
            wx.LC_HRULES | wx.LC_SINGLE_SEL | ULC.ULC_HAS_VARIABLE_ROW_HEIGHT)

        self.Bind(wx.EVT_LIST_COL_CLICK, self.OnColClick, lst)

        lst.InsertColumn(0, "Title")
        lst.InsertColumn(1, "Rating")
        lst.InsertColumn(2, "Year")
        lst.InsertColumn(3, "Genre")
        lst.InsertColumn(4, "Runtime")
        lst.InsertColumn(5, "Details")

        lst.SetColumnWidth(0, 100)
        lst.SetColumnWidth(1, 50)
        lst.SetColumnWidth(2, 50)
        lst.SetColumnWidth(3, 100)
        lst.SetColumnWidth(4, 100)
        lst.SetColumnWidth(5, -3)

        return lst

    def add_menu(self):
        menuBar = wx.MenuBar()
        menu = wx.Menu()

        m_open = menu.Append(wx.ID_OPEN, "&Open\tCtrl+O",
                             "Open a folder.")
        self.Bind(wx.EVT_MENU, self.open_folder, m_open)

        m_prefs = menu.Append(wx.ID_PREFERENCES, "&Preferences", "Preferences")
        self.Bind(wx.EVT_MENU, self.on_prefs, m_prefs)

        m_exit = menu.Append(wx.ID_EXIT, "&Exit\tCtrl+Q", "Exit")
        self.Bind(wx.EVT_MENU, self.on_close, m_exit)

        menuBar.Append(menu, "&File")

        menu = wx.Menu()

        m_about = menu.Append(wx.ID_ANY, "&About",
                              "Information about this program")
        self.Bind(wx.EVT_MENU, self.on_about, m_about)

        m_upd = menu.Append(wx.ID_ANY, "&Check For Updates",
                              "Check For Updates")
        self.Bind(wx.EVT_MENU, self.on_chk_upd, m_upd)

        menuBar.Append(menu, "&Help")

        self.SetMenuBar(menuBar)

    def on_chk_upd(self, evt):
        check_for_updates(self, True)

    def on_prefs(self, evt):
        dlg = PrefsDialog(parent=self, items_map=config.prefs_item_map)
        dlg.ShowModal()
        dlg.Destroy()

    def open_folder(self, evt):
        dlg = wx.DirDialog(self, "Choose a directory:",
                          style=wx.DD_DEFAULT_STYLE
                           | wx.DD_DIR_MUST_EXIST
                           #| wx.DD_CHANGE_DIR
                           )

        if dlg.ShowModal() == wx.ID_OK:
            target_dir = dlg.GetPath()
        else:
            return

        dlg.Destroy()

        #create new lst
        self.itemDataMap.clear()
        self.lst.Destroy()
        self.lst = self.build_list()
        ColumnSorterMixin.__init__(self, 6)
        self.sizer.Add(self.lst, 1, wx.EXPAND)
        self.Layout()
        self.Refresh()

        # switch to this dir
        self.total_rows = 0
        self.update_sb()
        os.chdir(target_dir)

        files_with_data, files_wo_data = process_dir('.', self.conn, self.cur)

        for f in files_with_data:
            self.add_row(f)

        if len(files_wo_data) > 0:
            start_dbbuilder(self, files_wo_data)

    def on_about(self, evt):
        abt_dlg = HtmlDialog(self, content=config.abt_dlg_content)
        abt_dlg.ShowModal()
        abt_dlg.Destroy()

    def GetListCtrl(self):
        return self.lst

    def OnColClick(self, event):
        event.Skip()
        self.Refresh()

    def add_row(self, filename):
        # get info from db, build info panel, add to list, update
        # itemdatamap
        data = get_from_db(self.conn, self.cur, filename)

        index = self.lst.InsertStringItem(sys.maxint, data['title'])

        self.lst.SetItemData(index, index)
        self.itemDataMap[index] = (data['title'], data['rating'], data['year'],
            data['genre'], data['runtime'], data['title'])

        self.lst.SetStringItem(index, 1, unicode(data["rating"]))
        self.lst.SetStringItem(index, 2, unicode(data["year"]))
        self.lst.SetStringItem(index, 3, data["genre"])
        self.lst.SetStringItem(index, 4, data["runtime"])
        self.lst.SetItemWindow(index, 5, self.build_info_panel(data),
                expand=True)
        self.total_rows += 1
        self.update_sb()

    def update_sb(self):
        if (self.total_rows == 1):
            self.sb.SetStatusText("1 File", 1)
        else:
            self.sb.SetStatusText("{0} Files".format(self.total_rows), 1)

    def build_info_panel(self, data):
        html_win = ClickableHtmlWindow(self.lst, size=(-1, 180))
        html_win.attach_to_frame(self, 0)
                #style=wx.html.HW_SCROLLBAR_NEVER)

        html_text = u"<table><tr>"
        img_file = os.path.join(config.images_folder, data['filename'] + '.jpg')
        if os.path.exists(img_file):
            html_text += u'<td width="100" rowspan="2">\
                    <img src="{0}"></td>\n'.format(img_file)
        else:
            html_text += u'<td width="100" rowspan="2"></td>'

        # imdb icon
        html_text += u'<td><a href="http://imdb.com/title/{0}">\
                <img src="{1}"></a></td></tr>'.format(data['imdbID'],
                        config.get_resource('images', 'imdb-logo.png'))
        print html_text

        # details
        html_text += u"<tr><td>" + self.generate_label_text(data) + u"</td></tr>"
        html_text += u"</table>"

        html_win.SetPage(html_text)

        return html_win

    def make_wrappable(self, txt):
        wrap_points = ['.', '-', ']', ')']
        for point in wrap_points:
            txt = txt.replace(point, point + ' ')
        return txt

    def generate_label_text(self, data):
        data2 = [('Title', data['title']),
                ('Filename', self.make_wrappable(data['filename'])),
                ('Director', data['director']),
                ('Actors', data['actors']),
                ('Plot', data['plot']),
                ]

        res = u"<table cellspacing=0 cellpadding=2>"
        for item in data2:
            res += u'<tr valign="top"><td valign="top"><b>{0}</b></td>\
                    <td valign="top">{1}</td></tr>\n'.\
                    format(item[0], item[1])

        res += u"</table>"
        #print ''
        #print res
        return res

    def on_file_done(self, evt):
        print "event recieved containing", evt.filename
        self.add_row(evt.filename)
        self.db_thread.gui_ready.set()

    def on_show_msg(self, evt):
        if (evt.html):
            dlg = HtmlDialog(self, content=evt.content)
            dlg.ShowModal()
            dlg.Destroy()
        else:
            wx.MessageBox(evt.content['body'], evt.content['title'],
                    style=wx.OK | wx.CENTER, parent=self)


#HELPER FUNCTIONS#
def is_movie_file(filename):
    if (filename.split('.')[-1] in config.movie_formats):
        return True
    else:
        return False


def start_dbbuilder(frame, files_wo_data):
    if (frame.db_thread is not None):
        frame.db_thread.exit_now.set()
        frame.db_thread.gui_ready.set()
        frame.db_thread.join()

    threadpool = ThreadPool(config.imdb_thread_pool_size)
    frame.db_thread = DBbuilderThread(frame, files_wo_data, threadpool)
    frame.db_thread.start()


def process_dir(directory, conn, cur):
    files_with_data = []
    files_wo_data = []

    for fil in os.listdir(directory):
        if os.path.isdir(os.path.join(directory, fil)):
            fil_children = os.listdir(os.path.join(directory, fil))
            for c in fil_children:
                if is_movie_file(c):
                    if is_in_db(conn, cur, c):
                        files_with_data.append(c)
                    else:
                        files_wo_data.append(c)
        else:
            if is_movie_file(fil):
                if is_in_db(conn, cur, fil):
                    files_with_data.append(fil)
                else:
                    files_wo_data.append(fil)
    return files_with_data, files_wo_data


def check_and_setup():
    try: os.mkdir(config.mdb_dir)
    except OSError, e: pass

    try: os.mkdir(config.images_folder)
    except OSError, e: pass

    if (os.path.exists(config.db_file) and \
            config.config['db_version'] < config.db_version):
        # db_version is old, make new db file
        os.unlink(config.db_file)

    if (not os.path.exists(config.db_file)):
        create_db = True
    else:
        create_db = False

    conn = sqlite3.connect(config.db_file)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if (create_db):
        create_database(conn, cur)

        config.config['db_version'] = config.db_version
        config.config.write()
        config.post_process()

    return conn, cur


def check_for_updates(frame, force=False):
    if (frame.upd_thread is not None):
        frame.upd_thread.exit_now = True
        frame.upd_thread.join()

    frame.upd_thread = UpdateThread(frame, force)
    frame.upd_thread.start()


#MAIN#
def main():
    conn, cur = check_and_setup()
    if len(sys.argv) == 1:
        # no args, use curdir
        target_files = None
    else:
        target_files = sys.argv[1:]

    if (target_files is None):
        # use cwd as target_files
        files_with_data, files_wo_data = process_dir(u'.', conn, cur)
    else:
        files_with_data = []
        files_wo_data = []

        #target_files should be in cwd
        #make all target_files non_absolute
        for i in range(len(target_files)):
            target_files[i] = unicode(os.path.basename(target_files[i]), 'utf-8')

        for fil in target_files:
            if os.path.isdir(fil):
                f_with, f_wo = process_dir(fil, conn, cur)
                files_with_data.extend(f_with)
                files_wo_data.extend(f_wo)
            else:
                if is_movie_file(fil):
                    if is_in_db(conn, cur, fil):
                        files_with_data.append(fil)
                    else:
                        files_wo_data.append(fil)

    print 'files_with_data', files_with_data
    print 'files_wo_data', files_wo_data

    #spawn threads
    if (config.platform == 'windows' and config.config['debug']):
        app = wx.App(redirect=True)
    else:
        app = wx.App(redirect=False)

    if (not config.config['debug']):
        wx.Log_SetActiveTarget(wx.LogStderr())

    frame = MyFrame(None, conn, cur)

    check_for_updates(frame)

    app.SetTopWindow(frame)
    frame.Maximize()

    for f in files_with_data:
        frame.add_row(f)

    if len(files_wo_data) > 0:
        start_dbbuilder(frame, files_wo_data)

    frame.Show()
    frame.Layout()
    app.MainLoop()

if __name__ == '__main__':
    main()
