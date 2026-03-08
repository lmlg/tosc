from .base import BaseBackend
import threading

class InprocData:
  def __init__ (self):
    self.version = 0
    self.lock = threading.RLock ()
    self.cond = threading.Condition (self.lock)
    self.bvec = None
    self.notifier = None

class InprocBackend (BaseBackend):
  def __init__ (self, data = None):
    super().__init__ ()
    self.data = data or InprocData ()

  def copy (self):
    return InprocBackend (self.data)

  def read (self):
    data = self.data
    with data.lock:
      if data.bvec is None:
        return (None, None)
      return (data.version, data.bvec)

  def _notify (self, data, new):
    data.bvec = new
    data.version += 1
    data.notifier = self.unique_id
    data.cond.notify_all ()
    return data.version

  def write (self, new):
    data = self.data
    with data.lock:
      return self._notify (data, new)

  def try_write (self, new, expected):
    if expected is None:
      expected = 0

    data = self.data
    with data.lock:
      if data.version != expected:
        return (False, data.version)
      return (True, self._notify (data, new))

  def target_wait (self):
    data = self.data
    version = data.version

    with data.lock:
      while version == data.version:
        data.cond.wait ()
      return version < data.version and data.notifier != self.unique_id

  def exclusive_lock (self):
    return self.data.lock.acquire ()

  def exclusive_unlock (self):
    return self.data.lock.release ()
