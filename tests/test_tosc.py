import tosc

import pytest

import threading
import time

def _make_mgr ():
  return tosc.Manager (tosc.InprocBackend ())

def tst_dpickler (mgr, obj):
  assert mgr.load (mgr.dump (obj)) == obj

def test_dpickler ():
  mgr = _make_mgr ()
  for x in (1, 3.14, 'abcdef', (1, 3.14, 'abcdef'),
            [1, 3.14, 'abcdef'], {'a': 1, 'b': 2},
            b"abcdef", bytearray ([1, 2, 3]), None,
            set ([1, 3.14, 'abcdef']), 1 << 40,
            frozenset ([1, 3.14, 'abcdef'])):
    tst_dpickler (mgr, x)

def test_dlist_api ():
  x = tosc.DList ([1, 2, 3])
  x.append (4)
  assert x == [1, 2, 3, 4]
  assert x.copy () == [1, 2, 3, 4]
  x.extend ([3, 4])
  assert x.count (1) == 1
  assert x.count (3) == 2
  assert x.index (2) == 1
  with pytest.raises (ValueError):
    x.index ('a')

  x.insert (2, -1)
  assert x[2] == -1
  assert x.pop () == 4
  assert x.pop (0) == 1
  x.remove (3)
  assert x.count (3) == 1

  with pytest.raises (ValueError):
    x.remove ('a')

  rev = list (reversed (x))
  x.reverse ()
  assert x == rev

  x.clear ()
  assert not x

  x = tosc.DList ([1, 2, 3])
  assert x + x == list (x) + list (x)
  assert x * 2 == list (x) * 2

  x += [4]
  assert x == [1, 2, 3, 4]
  x *= 2
  assert x == [1, 2, 3, 4, 1, 2, 3, 4]
  assert x[1:5:3] == list(x)[1:5:3]

def test_ddict_api ():
  x = tosc.DDict ({'a': 1, 'b': 2})
  assert x == x.copy ()
  assert x.get ('c') is None
  assert x.get ('a') == 1

  assert set (x.keys ()) == set (['a', 'b'])
  assert set (x.values ()) == set ([1, 2])
  assert set (x.items ()) == set ([('a', 1), ('b', 2)])

  x.update ({'c': 3})
  assert 'c' in x
  assert x['c'] == 3
  assert x.popitem () == ('c', 3)

  x.setdefault ('b', -1)
  assert x == {'a': 1, 'b': 2}
  x.setdefault ('c', -1)
  assert x['c'] == -1
  assert x.pop ('c') == -1
  assert x.pop ('q', None) is None

  x.clear ()
  assert not x

def test_dset_api ():
  x = tosc.DSet ([1, 2, 3, 4])
  assert 1 in x
  assert 'a' not in x
  x.add (5)
  assert 5 in x
  assert x.copy () == set (x)

  assert x.difference ([2, 4]) == set ([1, 3, 5])
  assert x.difference ([-1]) == x
  assert x - tosc.DSet ([2, 4]) == set ([1, 3, 5])
  assert x - tosc.DSet ([-1]) == x

  assert x.union ([6, 7]) == set ([1, 2, 3, 4, 5, 6, 7])
  assert x.union ([]) == x
  assert x.union ([1, 2]) == x
  assert x | tosc.DSet ([6, 7]) == set ([1, 2, 3, 4, 5, 6, 7])
  assert x | tosc.DSet ([]) == x
  assert x | tosc.DSet ([1, 2]) == x

  assert x.intersection ([2, 4]) == set ([2, 4])
  assert x.intersection ([6, 7]) == set ([])
  assert x.intersection (x) == x
  assert x & tosc.DSet ([2, 4]) == set ([2, 4])
  assert x & tosc.DSet ([6, 7]) == set ([])
  assert x & x == x

  assert x.symmetric_difference ([3, 4, -1]) == set ([1, 2, 5, -1])
  assert x.symmetric_difference (x) == set ([])
  assert x ^ tosc.DSet ([3, 4, -1]) == set ([1, 2, 5, -1])
  assert x ^ x == set ([])

  orig = x.copy ()
  x.difference_update (set ([2, 4]))
  assert x == set ([1, 3, 5])
  x = tosc.DSet (orig.copy ())
  x -= set ([2, 4])
  assert x == set ([1, 3, 5])

  x = tosc.DSet (orig.copy ())
  x |= set ([6, 7])
  assert x == set ([1, 2, 3, 4, 5, 6, 7])
  x = tosc.DSet (orig.copy ())

  x.intersection_update (set ([1, 2]))
  assert x == set ([1, 2])
  x = tosc.DSet (orig.copy ())
  x &= set ([1, 2])
  assert x == set ([1, 2])
  x = tosc.DSet (orig.copy ())

  x.symmetric_difference_update (set ([1, 2, -1]))
  assert x == set ([3, 4, 5, -1])
  x = tosc.DSet (orig.copy ())
  x ^= set ([1, 2, -1])
  assert x == set ([3, 4, 5, -1])

  x.clear ()
  assert not x

class Custom:
  def __init__ (self, x, y):
    self.x = x
    self.y = y

  def fn (self, arg):
    return (self.x, self.y, arg)

def test_pickle_custom ():
  mgr = _make_mgr ()
  c = Custom ('abc', [33])
  mgr.write (c)
  c2 = mgr.read ()
  c2.y[0] -= 33
  c.y[0] -= 33
  c.x = c2.x = '???'
  assert c2.fn (-1) == c.fn (-1)

def test_simple_modification ():
  mgr = _make_mgr ()
  mgr.write ({'a': 1, 'b': None})
  x = mgr.read ()
  it = iter (x)
  del x['a']
  assert 'a' in it

def test_concurrent_modification ():
  mgr = _make_mgr ()
  orig = [1, 2, 3]
  mgr.write (orig)
  lst = mgr.read ()

  def _inner_thread (mgr, child_ev, parent_ev):
    child_ev.wait ()
    mgr.read()[0] -= 1
    parent_ev.set ()

  with mgr.transaction ():
    child_ev = threading.Event ()
    parent_ev = threading.Event ()
    thr = threading.Thread (target = _inner_thread,
                            args = (mgr, child_ev, parent_ev),
                            daemon = True)
    thr.start ()
    it = iter (lst)
    child_ev.set ()
    parent_ev.wait ()
    # The newly spawned thread has modified the distributed list.
    # However, since we're inside a transaction, those changes
    # will not be visible.
    assert list (it) == orig

  # Outside the transaction, the changes must be reflected.
  assert mgr.refresh () != orig

def test_detached_object ():
  mgr = _make_mgr ()
  orig = [1, (2, 3), 4]
  mgr.write (orig)
  x = mgr.read ()
  sub = x[1]
  x[1] = None
  mgr.refresh ()
  assert not mgr.is_linked (sub)

def tst_transaction_error (action, exc_type, kwargs):
  mgr = _make_mgr ()
  mgr.write ([1, 2, 3])

  def _inner_thread (event, backend):
    mgr = tosc.Manager (backend.copy ())
    mgr.read()[0] = None
    event.set ()

  event = threading.Event ()
  thr = threading.Thread (target = _inner_thread,
                          args = (event, mgr.backend),
                          daemon = True)

  @tosc.transactional (mgr, **kwargs)
  def transaction ():
    thr.start ()
    event.wait ()
    mgr.read()[0] = -1
    if action:
      action ()

  with pytest.raises (exc_type):
    transaction ()

def test_transaction_timeout ():
  tst_transaction_error (lambda: time.sleep (0.15),
                         tosc.TransactionTimeoutError,
                         {'timeout': 0.1})

def test_transaction_retries_exceeded ():
  tst_transaction_error (None, tosc.TransactionRetryError,
                         {'retries': 0})

def test_transaction_rollback_on_exc ():
  mgr = _make_mgr ()
  orig = [1, 2, 3]
  mgr.write (orig)
  x = mgr.read ()

  try:
    with mgr.transaction ():
      x[0] -= 1
      raise KeyError ('???')
  except KeyError:
    pass

  assert x == orig
