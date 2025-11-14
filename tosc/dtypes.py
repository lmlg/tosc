from copy import copy as shallow_copy

class DObject:
  BASE_TYPE = object

  def __init__ (self, subobj, xid = 0, dmgr = None):
    if isinstance (subobj, DObject):
      self.subobj = subobj.subobj
      self.dmgr = subobj.dmgr
      self.xid = subobj.xid
      self.version = subobj.version
    else:
      if not isinstance (subobj, self.BASE_TYPE):
        subobj = self.BASE_TYPE (subobj)

      self.subobj = subobj
      self.dmgr = dmgr
      self.xid = xid
      self.version = 0 if dmgr is None else dmgr.version

  def __getstate__ (self):
    return (self.subobj, self.xid, self.dmgr)

  def __setstate__ (self, state):
    self.subobj, self.xid, self.dmgr = state
    self.dmgr.link (self)

def _ensure_latest_subobj (self):
  dmgr = self.dmgr
  if dmgr is None or self.version == dmgr.version:
    # Detached or up-to-date object.
    return self.subobj

  oget = dmgr.objmap.get
  while True:
    version = dmgr.version
    d_obj = oget (self.xid)
    if d_obj is None:
      # Object is detached.
      self.dmgr = None
      return self.subobj

    subobj = d_obj.subobj
    if version == dmgr.version:
      self.subobj = subobj
      self.version = version
      return subobj

def _call_with_latest (self, method, args, kwargs):
  dmgr = self.dmgr
  if dmgr is None:
    return method (self.subobj, *args, **kwargs)

  oget = dmgr.objmap.get
  xid = self.xid

  if self.version == dmgr.version:
    # Fast path: The version is up to date.
    d_obj = oget (xid)
    trace = False
    prev = None

    if d_obj is None:
      # ... But the object was detached.
      self.dmgr = None
      return method (self.subobj, *args, **kwargs)
    elif not dmgr.is_dirty (self):
      # Sub-object hasn't changed - Make a copy.
      prev = self.subobj
      self.subobj = shallow_copy (prev)
      trace = True

    ret = method (self.subobj, *args, **kwargs)
    if trace:
      with dmgr.transaction () as tr:
        tr.trace_obj (self, prev)

    return ret

  # We must atomically update the object and then run the method.
  version = dmgr.version
  while True:
    d_obj = oget (xid)
    if d_obj is None:
      # Object was detached.
      self.dmgr = None
      return method (self.subobj, *args, **kwargs)

    subobj = d_obj.subobj
    if version != dmgr.version:
      version = dmgr.version
      continue

    self.version = version
    prev = subobj
    self.subobj = shallow_copy (subobj)
    ret = method (self.subobj, *args, **kwargs)
    with dmgr.transaction () as tr:
      tr.trace_obj (self, prev)
      return ret

def _make_method (attr, is_op):
  if is_op:
    # Operators need to be handled separatedly, as their argument list may be
    # swapped and because they need to work on the underlying subobject for
    # both arguments.
    def _inner (self, arg):
      if isinstance (arg, DObject):
        arg = _ensure_latest_subobj (arg)
      if isinstance (self, DObject):
        self = _ensure_latest_subobj (self)
      return attr (self, arg)
    return _inner

  def _inner (self, *args, **kwargs):
    return attr (_ensure_latest_subobj (self), *args, **kwargs)
  return _inner

def _make_mutable_method (attr):
  def _inner (self, *args, **kwargs):
    return _call_with_latest (self, attr, args, kwargs)
  return _inner

_SKIP_ATTRS = ('__class__', '__init__', '__new__', '__setattr__',
               '__getattr__', '__getattribute__', '__call__',
               '__getstate__', '__setstate__', '__reduce__', '__reduce_ex__')

_OPERATORS = ('__eq__', '__lt__', '__gt__', '__le__', '__ge__',
              '__add__', '__sub__', '__mul__', '__and__', '__or__',
              '__xor__', '__radd__', '__rsub__','__rmul__','__rand__',
              '__rior__', '__rxor__')

_MUTABLES = ('append', 'clear', 'extend', 'insert', 'pop', 'remove',
             'reverse', 'sort',   # list
             'popitem', 'update', 'setdefault',   # dict
             'add', 'symmetric_difference_update', 'difference_update',
             'intersection_update', 'discard',   # set
             '__setitem__', '__delitem__', '__iadd__', '__imul__',
             '__iand__', '__ior__', '__ixor__')

def _make_dbuiltin (base, name):
  ret = type (name, (DObject,), {})
  for elem in dir (base):
    if elem in _SKIP_ATTRS:
      continue
    attr = getattr (base, elem)
    stype = str (type (attr))
    if 'wrapper' not in stype and 'method' not in stype:
      # Attribute is not a methor or method-wrapper - Skip.
      continue
    elif elem in _MUTABLES:
      setattr (ret, elem, _make_mutable_method (attr))
    else:
      setattr (ret, elem, _make_method (attr, elem in _OPERATORS))

  ret.BASE_TYPE = base
  return ret

DList = _make_dbuiltin (list, 'DList')
DSet = _make_dbuiltin (set, 'DSet')
DDict = _make_dbuiltin (dict, 'DDict')
DByteArray = _make_dbuiltin (bytearray, 'DByteArray')

class DAny:
  """
  Distributed 'Any' type - This is the base class of non-builtin types that
  are pickled by the distributed sub-classes. The class itself is only used
  to control what '__setstate__' does - Because the descriptors are linked to
  the distributed manager upon object creation, we don't need to do anything
  else here. However, since arbitrary objects can be pickled, we need to
  overwrite this method here to prevent further code from being executed.
  """

  def __setstate__ (self, dmgr):
    pass

class DDescriptor:
  """
  Distributed descriptor. Instances of this class represent the attributes of
  instances of the type 'DAny'. The only important bit of note is that the
  '__set__' method calls out to the distributed manager to notify of changes.
  """

  def __init__ (self, values, index):
    self.values = values
    self.index = index

  def __get__ (self, obj, _):
    return self if obj is None else self.values[self.index]

  def __set__ (self, _, value):
    self.values[self.index] = value
