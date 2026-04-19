from .dtypes import *

import io
from pickle import (dumps, loads, Pickler, Unpickler)

_DBUILTIN_MAP = {
  list: DList,
  set: DSet,
  dict: DDict,
  bytearray: DByteArray,
}

def _make_any (typ, attrs, dmgr, values):
  if values is None:
    values = DList (list (attrs.values ()))
    dmgr.link (values)

  descriptors = {k: DDescriptor (values, index)
                 for index, k in enumerate (attrs)}

  ntype = type ("distributed-" + typ.__name__, (typ, DAny), descriptors)
  ntype.__slots__ = tuple (descriptors.keys ())
  return ntype.__new__ (ntype)

def _make_xmethod (method):
  return lambda self, *args, **kwargs: method (self.subobj, *args, **kwargs)

def _make_xtype (bvec):
  obj = loads (bvec)
  otype = type (obj)
  ntype = type ("distributed-" + otype.__name__, (DXtype,), {})
  ntype.__slots__ = ("subobj",)

  for attr in dir (otype):
    if attr in SKIP_ATTRS:
      continue

    method = getattr (otype, attr)
    setattr (ntype, attr, _make_xmethod (method))

  ret = ntype.__new__ (ntype)
  ret.subobj = obj
  return ret

# These types and functions don't need to be maintained externally from
# picklers, but it's useful to do so to keep the resulting byte array small
# since they are called a lot.
_DTYPES = (DList, DSet, DDict, DByteArray, DObject, _make_any, _make_xtype)

class DPickler (Pickler):
  def __init__ (self, fileobj, dmgr):
    super().__init__ (fileobj)
    self.dmgr = dmgr

  def persistent_id (self, obj):
    if obj is self.dmgr:
      return -1

    try:
      return _DTYPES.index (obj)
    except (ValueError, TypeError):
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
  def __init__ (self, typ, attrs, dmgr, values = None):
    self._type = typ
    self._attrs = attrs
    self._dmgr = dmgr
    self._values = values

  def __reduce__ (self):
    return (_make_any, (self._type, self._attrs,
                        self._dmgr, self._values), self._dmgr)

class _XWrapper:
  def __init__ (self, obj):
    self.obj = obj.subobj if isinstance (obj, DXtype) else obj

  def __reduce__ (self):
    return (_make_xtype, (dumps (self.obj),), None)

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

  values = None

  if isinstance (obj, DAny):
    # The MRO looks something like this: [..., actual-type, DAny, object]
    # As such, index -3 is the one to fetch to get the desired type.
    ty = ty.__mro__[-3]
    slots = getattr (obj, '__slots__', None)
    if slots:
      values = getattr(type (obj), slots[0]).values

  try:
    return _Wrapper (ty, _obj_attrs (obj), dmgr, values)
  except TypeError:
    return _XWrapper (obj)
