from time import time

class TransactionError (Exception):
  pass

class TransactionRetryError (Exception):
  pass

class TransactionTimeoutError (Exception):
  pass

class Transaction:
  def __init__ (self, dmgr):
    self.objs = {}
    self.dmgr = dmgr
    self.depth = 0
    self.version = 0

  def trace_obj (self, obj, prev):
    """
    Mark an object as being a part of the transaction.
    """
    self.objs[obj.xid] = (obj, prev)

  def is_traced (self, obj):
    """
    Test whether an object is a part of the transaction.
    """
    return obj.xid in self.objs

  def rollback (self):
    """
    Undo the changes proposed by the transaction.
    """
    objmap = self.dmgr.objmap
    for xid, prev in self.objs.items ():
      prev_obj, prev_val = prev
      objmap[prev_obj.xid].subobj = prev_obj.subobj = prev_val

  def commit (self):
    """
    Apply the changes proposed by the transaction.
    """
    objs = self.objs
    if not objs:
      return True

    dmgr = self.dmgr
    outmap = dmgr.objmap

    for xid, val in objs.items ():
      outmap[xid].subobj = val[0].subobj

    try:
      ret = dmgr.try_write (dmgr.root_obj, self.version)
    except Exception:
      ret = False

    if not ret:
      self.rollback ()

    return ret

  def __enter__ (self):
    if self.depth == 0:
      self.version = self.dmgr.version
    self.depth += 1
    return self

  def unlink (self):
    """
    Remove the transaction from the underlying Manager.
    """
    self.objs.clear ()
    self.dmgr.unlink_trans ()

  def __exit__ (self, exc_type, *args):
    self.depth -= 1
    if self.depth == 0:
      if exc_type is not None:
        # If an unrelated exception was raised, we have to
        # unconditionally rollback the transaction.
        self.rollback ()
        self.unlink ()
      else:
        rv = self.commit ()
        self.unlink ()
        if not rv:
          raise TransactionError ('failed to commit transaction '
                                  'due to version mismatch')
    return False

def transactional (dmgr, retries = None, timeout = None):
  if retries is not None and (not isinstance (retries, int) or retries < 0):
    raise ValueError ('retries must be a positive integer')

  if timeout is not None:
    if (not isinstance (timeout, int) and
        not isinstance (timeout, float)) or timeout < 0:
      raise ValueError ('timeout must be a positive number')

  def _inner (fn):
    def _f (*args, **kwargs):
      num_retries = retries
      deadline = None if timeout is None else time () + timeout

      while True:
        try:
          with dmgr.transaction ():
            return fn (*args, **kwargs)
        except TransactionError:
          pass

        if num_retries is not None:
          num_retries -= 1
          if num_retries <= 0:
            raise TransactionRetryError ()

        if deadline is not None and time () > deadline:
          raise TransactionTimeoutError ()

    return _f
  return _inner
