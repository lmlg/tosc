from .dpickler import (DObject, DPickler, DUnpickler, make_pickable)
from .transaction import Transaction

from copy import deepcopy
import io
import threading
import uuid
import weakref

NIL = object ()

class Manager:
  def __init__ (self, backend):
    self.unique_id = str(uuid.uuid4 ()).replace('-', '').encode ('utf8')
    self.backend = backend
    self.backend.set_id (self.unique_id)
    self.iov = io.BytesIO ()
    self.root_obj = NIL
    self._xid = 1
    self.objmap = {}
    self.new_objmap = self.objmap
    self.cur_trans = None
    self.lock = threading.Lock ()
    self.needs_update = False
    self.version = 0
    self._saved_tr = Transaction (self)
    self.watcher = threading.Thread (target = self.watcher_target,
                                     args = (weakref.ref (self),),
                                     daemon = True)
    self.watcher.start ()

  @property
  def xid (self):
    """
    Return a unique identifier for a distributed object, but only from
    this Manager's point of view.
    """
    ret = self._xid
    self._xid += 1
    return ret

  def is_linked (self, obj):
    """
    Test whether an object is being managed by this instance.
    """
    return isinstance (obj, DObject) and obj.xid in self.objmap

  def is_dirty (self, obj):
    """
    Test if an object is 'dirty' - that is, if this Manager is in the middle
    of a transaction, and changes on the object have not been commited yet.
    """
    tr = self.cur_trans
    return (tr is not None and isinstance (obj, DObject) and
            tr.is_traced (obj))

  @staticmethod
  def watcher_target (wself):
    """
    Watch for changes on the underlying backend from a separate thread.
    """
    while True:
      self = wself ()
      if self is None:
        return

      if self.backend.target_wait ():
        with self.lock:
          if self.cur_trans is not None:
            # If a transaction is in flight, simply mark the current
            # status as needing an update.
            self.needs_update = True
          else:
            # Otherwise, refresh the root object.
            self._refresh_locked (None)

  def transaction (self):
    """
    Initiate a transaction on this Manager. This call can be nested.
    """
    ret = self._saved_tr
    if ret is not self.cur_trans:
      with self.lock:
        self.cur_trans = ret
    return ret

  def unlink_trans (self):
    """
    Mark this Manager as having no ongoing transaction.
    """
    if self.needs_update:
      self._refresh_locked (None)
    self.cur_trans = None

  def link (self, obj):
    """
    Make an object managed by this instance.
    """
    xid = obj.xid
    if xid == 0:
      obj.xid = xid = self.xid
    else:
      tmp = self.new_objmap.get (xid)
      if tmp is not None and tmp is not obj:
        raise ValueError ('duplicate ID (%d) for object' % xid)

    obj.version = self.version
    self.new_objmap[xid] = obj

  def _refresh_locked (self, dfl):
    version, payload = self.backend.read ()
    if version is None:
      return dfl
    elif self.version >= version:
      return self.root_obj

    self.version = version
    self.needs_update = False
    self.root_obj = self._load (payload)
    self.objmap = self.new_objmap
    return self.root_obj

  def refresh (self, dfl = None):
    """
    Fetch the latest stored object from the backend.
    """
    with self.transaction ():
      return self._refresh_locked (dfl)

  def read (self, dfl = None):
    """
    Get the cached root object from this Manager, or get it from the
    backend if nothing is cached.
    """
    ret = self.root_obj
    if ret is NIL:
      ret = self.refresh (dfl)
    return ret

  def _payload (self, obj):
    iov = self.iov
    iov.seek (0)
    iov.truncate (0)
    DPickler(iov, self).dump (make_pickable (obj, self))
    return iov.getvalue ()

  def _load (self, payload):
    self.new_objmap = {}
    return DUnpickler(io.BytesIO (payload), self).load ()

  def _update (self, version, root):
    if version > self.version:
      self.version = version
      self.root_obj = root
      self.objmap = self.new_objmap

  def write (self, obj):
    """
    Replace the stored object in the backend with a new one.
    """
    payload = self._payload (obj)
    version = self.backend.write (payload)
    root = self._load (payload)
    with self.lock:
      self._update (version, root)

  def try_write (self, obj, exp_version = None):
    """
    Compare the version stored in the backend with an expected value and
    replace the object stored with a new one if it matches.
    """
    if exp_version is None:
      exp_version = self.version

    payload = self._payload (obj)
    ret, version = self.backend.try_write (payload, exp_version)
    if ret:
      root = self._load (payload)
      with self.lock:
        self._update (version, root)
    return ret

  def dump (self, obj):
    self.iov.seek (0)
    self.iov.truncate (0)
    DPickler(self.iov, self).dump (make_pickable (obj, self))
    return self.iov.getvalue ()

  def load (self, payload = None):
    return DUnpickler(io.BytesIO (payload), self).load ()

  def __getstate__ (self):
    raise ValueError ('distributed managers must not be pickled')

  def snapshot (self, dfl = None):
    """
    Create a snapshot of the current stored object.
    """
    with self.transaction ():
      return dfl if self.root_obj is NIL else deepcopy (self.root_obj)
