from .base import BaseBackend
from filelock import FileLock
import os
from struct import pack, unpack
from subprocess import check_output, DEVNULL
from tempfile import NamedTemporaryFile
from time import sleep
import sys

try:
  from tempfile import _TemporaryFileWrapper
except ImportError:
  _TemporaryFileWrapper = None

# Time in seconds to wait sleep before polling for a FS event.
# The selected value will depend on whether the filesystem is
# local or not.
_DFL_STAT_INTERVAL = 5
_MAX_STAT_INTERVAL = 30
_MIN_STAT_INTERVAL = 0.2

_LOCAL_FS = frozenset ([
  0x1373,       # devfs
  0x4006,       # fat
  0x4d44,       # msdos
  0xEF53,       # ext2/3
  0x72b6,       # jffs2
  0x858458f6,   # ramfs
  0x5346544e,   # ntfs
  0x3153464a,   # jjs
  0x9123683e,   # btrfs
  0x52654973,   # reiser3
  0x01021994,   # tmpfs
  0x58465342,   # xfs
])

def _patched_tempfile_exit (*args):
  try:
    # The tempfile was renamed and no longer exists.
    # On older Python versions, this caused issues,
    # so patch it out here.
    _TemporaryFileWrapper.__exit__ (*args)
  except FileNotFoundError:
    pass

class FileBackend (BaseBackend):
  def __init__ (self, path, lock_path = None):
    super().__init__ ()
    self.path = path
    self._last_modified = None
    self.lock_path = lock_path or (path + '.lock')
    self.lock = FileLock (self.lock_path)
    self._start ()
    self.interval = _DFL_STAT_INTERVAL
    self.dir_path = os.path.dirname (path)

    if os.name == 'posix':
      self._determine_stat_interval ()

  def _tempfile (self):
    ret = NamedTemporaryFile (dir = self.dir_path)
    if _TemporaryFileWrapper is not None:
      ret.__exit__ = _patched_tempfile_exit
    return ret

  def copy (self):
    return FileBackend (self.path, self.lock_path)

  def _determine_stat_interval (self):
    try:
      # XXX: Using statfs would be much easier, but unfortunately,
      # the interface in the std lib doesn't have access to the
      # 'f_type' member, which is what we need.
      ret = check_output (['stat', '-f', '-c', '%t',
                           os.path.dirname (self.path)],
                          text = True, stderr = DEVNULL)
      fstype = int (ret.strip (), 16)
      if fstype in _LOCAL_FS:
        self.interval = _MIN_STAT_INTERVAL
      else:
        self.interval = _MAX_STAT_INTERVAL
    except Exception:
      pass

  def _start (self):
    try:
      self._last_modified = os.stat(self.path).st_mtime
    except FileNotFoundError:
      pass

  def _get_version (self):
    try:
      with open (self.path, 'rb') as f:
        return unpack("<Q", f.read (8))[0]
    except FileNotFoundError:
      return 0

  def read (self):
    try:
      with open (self.path, 'rb') as file:
        version, _ = unpack ("<Q32s", file.read (40))
        return (version, file.read ())
    except FileNotFoundError:
      return (0, None)

  def link (self, tpath):
    os.rename (tpath, self.path)

  def write (self, new):
    with self.lock, self._tempfile () as fm:
      version = self._get_version () + 1
      fm.write (pack ("<Q32s", version, self.unique_id))
      fm.write (new)
      self.link (fm.name)
      return version

  def try_write (self, new, expected):
    with self.lock, self._tempfile () as fm:
      version = self._get_version ()
      if version != expected:
        return (False, version)

      expected += 1
      fm.write (pack ("<Q32s", expected, self.unique_id))
      fm.write (new)
      self.link (fm.name)
      return (True, expected)

  def target_wait (self):
    sleep (self.interval)
    prev = self._last_modified
    try:
      with open (self.path, 'rb') as file:
        _, uid = unpack ("<Q32s", file.read (40))
        self._last_modified = os.fstat(file.fileno ()).st_mtime
        return (prev is None) or (
            self._last_modified > prev and uid != self.unique_id)
    except Exception:
      return False
