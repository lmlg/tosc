from .base import BaseBackend
from rados import (Rados, ObjectNotFound, ObjectExists, OSError as RadosError)
from struct import pack, unpack_from
from threading import Condition, Lock
from time import sleep

def _on_write (comp, retval, ack_list, timeouts):
  # Nothing to do.
  pass

class CephBackend (BaseBackend):
  def __init__ (self, client, key, mon_host, pool_name,
                obj_name, max_retries = 100):

    if not isinstance (max_retries, int) or max_retries < 1:
      raise ValueError ('max_retries must be at least 1')

    if not isinstance (obj_name, str) or not obj_name:
      raise ValueError ('obj_name must be a non-empty string')

    super().__init__ ()
    cluster = Rados (name = 'client.' + client,
                     conf = dict (key = key, mon_host = mon_host))
    cluster.connect ()

    try:
      self.ioctx = cluster.open_ioctx (pool_name)
    except Exception:
      cluster.shutdown ()
      raise

    self.cluster = cluster
    self.obj_name = obj_name
    self.max_retries = max_retries
    self.lock = Lock ()
    self.cond = Condition (self.lock)
    self.recv_id = None
    self.watch = None

    self._watch ()
    try:
      self._update_version ()
    except Exception:
      self.version = 0

  def _watch (self):
    if self.watch is not None:
      return

    try:
      self.watch = self.ioctx.watch (self.obj_name, self.on_complete,
                                     self.on_notify_error)
    except ObjectNotFound:
      pass

  def __del__ (self):
    try:
      self.ioctx.close ()
    except Exception:
      pass

    watch = getattr (self, 'watch', None)
    if watch is not None:
      try:
        self.watch.close ()
      except Exception:
        pass

    try:
      self.cluster.shutdown ()
    except Exception:
      pass

    self.ioctx = None
    self.watch = None
    self.cluster = None

  def _update_version (self):
    self.version = self.ioctx.get_last_version ()
    return self.version

  def read (self):
    n = self.max_retries
    while n >= 0:
      n -= 1
      try:
        size = self.ioctx.stat(self.obj_name)[0]
        ret = memoryview (self.ioctx.read (self.obj_name, size))
        obj_size = unpack_from("<Q", ret)[0]
        if obj_size + 8 <= size:
          return (self._update_version (), ret[8:obj_size + 8])
      except ObjectNotFound:
        return (None, None)

    raise RuntimeError ('failed to get RADOS object')

  def _notify (self):
    ret = self._update_version ()
    self._watch ()
    try:
      # Don't worry if a notification cannot be queued. At some point,
      # either someone else will try to write to the object and Ceph
      # will raise a RADOS error - *or* - the call to 'stat' inside
      # 'target_wait' will be the one to detect a newer version.
      self.ioctx.aio_notify (self.obj_name, _on_write, self.unique_id or '')
    except Exception:
      pass

    return ret

  def write (self, new):
    self.ioctx.write_full (self.obj_name, pack ("<Q", len (new)) + new)
    return self._notify ()

  def try_write (self, new, expected):
    wop = self.ioctx.create_write_op ()
    try:
      if expected is not None:
        wop.assert_version (expected)
      else:
        wop.new (1)

      wop.write (pack ("<Q", len (new)))
      wop.write (new, 8)
      self.ioctx.operate_write_op (wop, self.obj_name)
      return (True, self._notify ())
    except (ObjectExists, RadosError):
      return (False, self._notify ())
    finally:
      wop.release ()

  def on_complete (self, notify_id, notifier, cookie, data):
    if isinstance (data, bytes):
      data = data.decode ('utf8')
    if data != self.unique_id:
      with self.lock:
        self.recv_id = data
        self.cond.notify ()

  def on_notify_error (self, *_):
    # The error callback can be invoked on a network error or if the
    # object no longer exists. In any case, we simply detach the
    # watcher object.
    try:
      self.watch.close ()
    except Exception:
      pass

    self.watch = None

  def target_wait (self):
    with self.lock:
      while self.recv_id is None:
        self.cond.wait (5)
      if self.recv_id is not None:
        ret = self.recv_id
        self.recv_id = None
        return ret

    try:
      self.ioctx.stat (self.obj_name)
      prev = self.version
      return self._update_version () != prev
    except Exception:
      return False
