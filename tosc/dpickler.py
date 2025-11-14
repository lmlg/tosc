from .dtypes import *

import io
from pickle import (Pickler, Unpickler, UnpicklingError)

_DBUILTIN_MAP = {
  list: DList,
  set: DSet,
  dict: DDict,
  bytearray: DByteArray,
}

def _make_any (typ, attrs, dmgr):
  values = DList (list (attrs.values ()))
  dmgr.link (values)

  descriptors = {k: DDescriptor (values, index)
                 for index, k in enumerate (attrs)}

  ntype = type ("distributed-" + typ.__name__, (typ, DAny), descriptors)
  ntype.__slots__ = tuple (descriptors.keys ())
  return ntype.__new__ (ntype)

# These types and functions don't need to be maintained externally from
# picklers, but it's useful to do so to keep the resulting byte array small
# since they are called a lot.
_DTYPES = (DList, DSet, DDict, DByteArray, DObject, _make_any)

class DPickler (Pickler):
  def __init__ (self, fileobj, dmgr):
    super().__init__ (fileobj)
    self.dmgr = dmgr

  def persistent_id (self, obj):
    if obj is self.dmgr:
      return -1

    try:
      return _DTYPES.index (obj)
    except ValueError:
      pass

class DUnpickler (Unpickler):
  def __init__ (self, fileobj, dmgr):
    super().__init__ (fileobj)
    self.dmgr = dmgr

  def persistent_load (self, pid):
    if pid == -1:
      return self.dmgr

    try:
      return _DTYPES[pid]
    except IndexError:
      pass

def _obj_attrs (obj):
  ret = getattr (obj, '__slots__', None)
  if ret is not None:
    return {k: getattr (obj, k) for k in ret}

  ret = getattr (obj, '__dict__', None)
  if ret is None:
    raise TypeError ('cannot get attributes of object of type %r' %
                     type (obj))

  return ret if isinstance (ret, dict) else dict (ret)

class _Wrapper:
  def __init__ (self, typ, attrs, dmgr):
    self._type = typ
    self._attrs = attrs
    self._dmgr = dmgr

  def __reduce__ (self):
    return (_make_any, (self._type, self._attrs, self._dmgr), self._dmgr)

def make_pickable (obj, dmgr):
  ty = type (obj)
  if (ty in (int, float, str, bytes, bool, tuple, frozenset) or
      obj is None or isinstance (obj, DObject)):
    return obj

  make = _DBUILTIN_MAP.get (ty)
  if ty in (list, set):
    return make (ty (make_pickable (x, dmgr) for x in obj), 0, dmgr)
  elif ty is dict:
    sub = dict ((make_pickable (k, dmgr), make_pickable (v, dmgr))
                for k, v in obj.items ())
    return make (sub, 0, dmgr)
  elif ty is bytearray:
    return make (obj, 0, dmgr)

  if isinstance (obj, DAny):
    ty = ty.__mro__[-3]

  return _Wrapper (ty, _obj_attrs (obj), dmgr)
