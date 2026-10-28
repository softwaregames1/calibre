#!/usr/bin/env python
# License: GPLv3 Copyright: 2026, softwaregames1

import json
import os
import posixpath

from calibre import prints
from calibre.utils.localization import _

readonly = False
version = 0  # change this if you change signature of implementation()
ACTIONS = ('list', 'extract', 'rename', 'remove')


def data_relpath(name: str) -> str:
    # Data files are specified relative to the data directory of the book and
    # must stay inside it
    from calibre.db.constants import DATA_DIR_NAME

    name = posixpath.normpath(name.replace(os.sep, '/').replace('\\', '/'))
    if not name or name in ('.', '..') or name.startswith(('/', '../')):
        raise ValueError(_('Not a valid data file name: {}').format(name))
    return f'{DATA_DIR_NAME}/{name}'


def implementation(db, notify_changes, action, book_id, *args):
    from calibre.db.constants import DATA_DIR_NAME, DATA_FILE_PATTERN

    is_remote = notify_changes is not None
    if not db.has_id(book_id):
        return False, _('No book with id: {}').format(book_id)
    try:
        relpaths = [data_relpath(x) for x in args[0]] if action in ('extract', 'rename', 'remove') else []
    except ValueError as e:
        return False, str(e)
    existing = {ef.relpath: ef for ef in db.list_extra_files(book_id, pattern=DATA_FILE_PATTERN)}
    if action == 'list':
        prefix = DATA_DIR_NAME + '/'
        return True, [(relpath[len(prefix) :], ef.stat_result.st_size, ef.stat_result.st_mtime) for relpath, ef in sorted(existing.items())]
    if missing := [x for x in relpaths if x not in existing]:
        return False, _('Book {0} has no data files named: {1}').format(book_id, ', '.join(x.partition('/')[2] for x in missing))
    if action == 'extract':
        relpath, dest = relpaths[0], args[1]
        if is_remote:
            with open(existing[relpath].file_path, 'rb') as f:
                return True, f.read()
        db.copy_extra_file_to(book_id, relpath, dest)
        return True, None
    if action == 'rename':
        src = relpaths[0]
        try:
            dest = data_relpath(args[1])
        except ValueError as e:
            return False, str(e)
        if not db.rename_extra_files(book_id, {src: dest}, replace=args[2]):
            return False, _('A data file named {} already exists').format(args[1])
        return True, None
    if action == 'remove':
        errors = {k: v for k, v in db.remove_extra_files(book_id, relpaths, permanent=is_remote or args[1]).items() if v is not None}
        if errors:
            return False, '\n'.join(f'{k.partition("/")[2]}: {getattr(v, "strerror", None) or v}' for k, v in errors.items())
        return True, len(relpaths)
    return False, _('Unknown action: {}').format(action)


def option_parser(get_parser, args):
    parser = get_parser(
        _(
            '''\
%prog data_files [options] (list|extract|rename|remove) book_id ...

Manage the data files of a book, that is the extra files stored in the data
folder of the book, as for the Manage data files tool in the calibre interface.
Files are specified by their names relative to the data folder. To add data
files, use: calibredb add_format --as-extra-data-file

List the data files of a book, with their sizes and modification times:

%prog data_files list book_id

Copy a data file out of the library, to the current folder or the folder specified with --to:

%prog data_files extract book_id name

Rename a data file, which can also move it into a sub-folder:

%prog data_files rename book_id name new_name

Remove data files. They are moved to the Recycle Bin, unless --permanent is used
or the library is on a Content server:

%prog data_files remove book_id name ...
'''
        )
    )
    parser.add_option(
        '--to',
        default=None,
        help=_('The folder to extract data files to, or the path to save the data file as. Default is the current folder'),
    )
    parser.add_option(
        '--replace',
        default=False,
        action='store_true',
        help=_('Replace existing files when extracting or renaming data files'),
    )
    parser.add_option(
        '--permanent',
        default=False,
        action='store_true',
        help=_('Do not use the Recycle Bin when removing data files'),
    )
    parser.add_option(
        '--for-machine',
        default=False,
        action='store_true',
        help=_('Generate output in JSON format, which is more suitable for machine parsing'),
    )
    return parser


def run(dbctx, *args):
    ok, ans = dbctx.run('data_files', *args)
    if not ok:
        raise SystemExit(ans)
    return ans


def main(opts, args, dbctx):
    from calibre.utils.date import as_local_time, utcfromtimestamp

    if len(args) < 2:
        raise SystemExit(_('Error: You must specify an action, one of: ({}) and a book id').format('|'.join(ACTIONS)))
    action, args = args[0], args[1:]
    if action not in ACTIONS:
        raise SystemExit(_('Error: Action {0} not recognized, must be one of: ({1})').format(action, '|'.join(ACTIONS)))
    try:
        book_id = int(args[0])
    except ValueError:
        raise SystemExit(_('Error: The book id must be a number'))
    names = args[1:]
    if action == 'list':
        if names:
            raise SystemExit(_('Error: Too many arguments: {}').format(' '.join(names)))
        files = run(dbctx, 'list', book_id)
        if opts.for_machine:
            prints(json.dumps([{'name': n, 'size': s, 'mtime': utcfromtimestamp(t).isoformat()} for n, s, t in files], indent=2))
        else:
            for n, s, t in files:
                prints(f'{n}\t{s}\t{as_local_time(utcfromtimestamp(t)).strftime("%Y-%m-%d %H:%M")}')
        return 0
    if action == 'extract':
        if len(names) != 1:
            raise SystemExit(_('Error: You must specify the name of one data file to extract'))
        dest = os.path.abspath(opts.to or os.getcwd())
        if os.path.isdir(dest):
            dest = os.path.join(dest, names[0].replace('\\', '/').rpartition('/')[2])
        if os.path.exists(dest) and not opts.replace:
            raise SystemExit(_('Error: {} already exists, use --replace to overwrite it').format(dest))
        data = run(dbctx, 'extract', book_id, names, dest)
        if data is not None:
            with open(dest, 'wb') as f:
                f.write(data)
        prints(dest)
        return 0
    if action == 'rename':
        if len(names) != 2:
            raise SystemExit(_('Error: You must specify the name of the data file and its new name'))
        run(dbctx, 'rename', book_id, names[:1], names[1], opts.replace)
        return 0
    if not names:
        raise SystemExit(_('Error: You must specify the names of the data files to remove'))
    count = run(dbctx, 'remove', book_id, names, opts.permanent)
    prints(_('{} data files removed').format(count))
    return 0
