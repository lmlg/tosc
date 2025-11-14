import os
import random
import select
import signal
import sys
import time

sys.path.append ('..')
import tosc

stop_flag = False
RUNTIME = 30.

def sigterm (sig, frame):
  global stop_flag
  stop_flag = True

class Data:
  def __init__ (self, balance):
    self.orig_balance = self.balance = balance
    self.num_withdrawals = 0
    self.num_failed_withdrawals = 0
    self.num_deposits = 0
    self.withdrew = 0
    self.deposited = 0
    self.withdrawals = []
    self.failed_withdrawals = []
    self.deposits = []

  def _add_list_entry (self, lst, val):
    ix = len (lst) + 1
    lst.append ({'value': val, 'index': ix})

  def _check_list (self, name):
    ixs = set ([])
    lst = getattr (self, name)

    for elem in lst:
      if elem['index'] in ixs:
        raise RuntimeError ('found duplicate index for list %s' % name)
      ixs.add (elem['index'])

    if lst and lst[-1]['index'] != len (lst):
      raise RuntimeError ('inconsistent length for list %s' % name)

  def withdraw (self, num):
    if self.balance > num:
      self.balance -= num
      self.withdrew += num
      self.num_withdrawals += 1
      self._add_list_entry (self.withdrawals, num)
    else:
      self.num_failed_withdrawals += 1
      self._add_list_entry (self.failed_withdrawals, num)

  def deposit (self, num):
    self.balance += num
    self.deposited += num
    self.num_deposits += 1
    self._add_list_entry (self.deposits, num)

  def check (self):
    if self.balance < 0:
      raise RuntimeError ('balance cannot be negative')
    if (self.num_withdrawals < 0 or self.num_failed_withdrawals < 0 or
        self.num_deposits < 0):
      raise RuntimeError ('counters cannot be negative')

    if self.orig_balance + self.deposited < self.withdrew:
      raise RuntimeError ('inconsistent balance')

    self._check_list ('withdrawals')
    self._check_list ('failed_withdrawals')
    self._check_list ('deposits')

FACTOR = 10000.

def run (mgr, fd):
  signal.signal (signal.SIGTERM, sigterm)
  select.select ((fd,), (), ())
  data = mgr.read ()

  def xsleep (secs):
    time.sleep (max (secs, 0.1) * 2)

  @tosc.transactional (mgr)
  def deposit (val):
    data.deposit (val)
    xsleep (val / FACTOR)

  @tosc.transactional (mgr)
  def withdraw (val):
    data.withdraw (val)
    xsleep (val / FACTOR)

  @tosc.transactional (mgr)
  def check (val):
    data.check ()
    xsleep (val / FACTOR)

  funcs = (deposit, withdraw, check)

  while not stop_flag:
    val = int (FACTOR * random.random ())
    funcs[val % 3] (val)

def main ():
  bname = sys.argv[1].lower ()
  if bname == 'ceph':
    make_backend = lambda: tosc.CephBackend (*sys.argv[2:8])
  elif bname == 'file':
    make_backend = lambda: tosc.FileBackend (sys.argv[2])
  else:
    raise RuntimeError ('invalid backend for functional test')

  fds = os.pipe ()
  pids = []

  for _ in range (5):
    pid = os.fork ()
    if pid == 0:
      run (tosc.Manager (make_backend ()), fds[0])
      sys.exit (0)
    else:
      pids.append (pid)

  try:
    mgr = tosc.Manager (make_backend ())
    mgr.write (Data (60000))
    os.write (fds[1], b'?')
    time.sleep (RUNTIME)
  finally:
    for pid in pids:
      os.kill (pid, signal.SIGTERM)
    for pid in pids:
      os.wait ()

if __name__ == '__main__':
  main ()
