## *tosc* --- Easy distributed data structures for Python

This library implements seamless distributed data structures for Python.
The aim is to let users write their programs in a normal, Pythonic fashion,
while at the same implementing all the constraints of a distributed system -
i.e: Data is always consistent across all the nodes, and changes are only
applied transactionally and atomically.

## Basic concepts

A normal workflow in _tosc_ is centered around the concept of a *Manager*, an
entity that makes sure that objects are kept consistent when mutating their
state. When instantiating managers, we need to select the *Backend* that will
be in charge of maintaining the _shared data_ itself. We can think of the
backend as an instance that is in charge of reading and writing data
atomically, whereas the manager consumes that data and propagates the changes.

### Example workflow

Here's a basic example program:

```python

import tosc

# Instantiate a manager with a backend
manager = tosc.Manager (tosc.FileBackend ('/tmp/some-file'))

# Write an object to the manager.
manager.write (some_object (...))

# Retrieve the object that was written.
obj = manager.read ()

# The object can now be manipulated in any way. The changes made
# to it will be applied transactionally, and any user holding
# references will be notified of said changes.
```

### Backends

As of the time of this writing, _tosc_ supports 3 backends:

* In-process backend (_tosc.InprocBackend_): This backend is only usable to
  share data across threads in the same process. Although not truly
  distributed, it's still useful if the user needs the properties of a
  distributed system, such as the possibility of applying changes atomically
  without the need for explicit threading primitives such as locks.

* File-based backend (_tosc.FileBackend_): This backend stores the data in
  a regular file. Changes are made atomic by virtue of filesystem semantics.
  The file used for the backing can be either local, or remote (as in NFS or
  Ceph-FS). In the latter case, this backend can be used to share data in a
  truly distributed way.

* Ceph-backend (_tosc.CephBackend_): The most scalable backend available, this
  one is only optionally built, in the presence of the _librbd_ and
  _librados_ libraries for Python.


## What can be written through a Manager?

As shown in the example above, we wrote some object to the instantiated Manager.
But _what exactly_ can be written? In short, any Python builtin type can be
shared, as well as any custom types, as long as they implement either the
`__dict__` or `__slots__` member.

It should be noted that the objects that are fetched after being written are
not identical type-wise. What this means is that if we write say, a list to
a _Manager_, if we afterwards fetch it, we will _not_ receive an object of the
same type. This is because the objects are wrapped to make sure that the new
types have distributed semantics and can receive changes that are made by other
processes in the distributed system.

## About distributed semantics and transactions

If we hold a distributed object and another process makes changes to it, we
will _eventually_ receive a notification and apply said changes in oder to
have the object display the updated state. This can lead to surprises as 
objects change underneath us without notice. In order to avoid these kinds
of surprises, we can make use of _transactions_.

For example:

```python
obj = manager.read ()

with manager.transaction () as tr:
  use_object_obj (obj)   # obj will not be affected by external changes.
```

As long as a transaction is ongoing, the manager will not apply any changes
made by external processes. If, on the other hand, _we_ mutate the state of
any distributed object, then once the transaction finishes, the manager will
see to it that the changes are propagated:

```python
obj = manager.read ()

with manager.transaction () as tr:
  mutate_object (obj)
  # once the transaction ends, the changes to `obj` will be sent through
  # the backend and to the other nodes in the system.
```

### Conflics with transactions

The above example leaves open the question of what happens if 2 different nodes
attempt to change the state at the same time. In that case, _tosc_ ensures that
only one process will succeed, and the others will see an exception raised,
indicating failure (_TransactionError_).

Naturally, it's a bit annoying to have transactions fail and having to retry
them manually. To avoid that, the library provides a decorator to do that
automatically:

```python
manager = tosc.Manager (...)

@tosc.transactional (manager)
def mutate_object (obj):
  # apply any changes to `obj` if conditions are met.

obj = manager.read ()

# Here, the function will be called repeteadly inside a transaction
# until no error is raised.
mutate_obj (obj)
```

As seen here, the mutator function is decorated so that it's retried in case
another process was just in the process of comitting a transaction itself.

## Wire format

It's been mentioned in this document that backends are in charge of storing
data so that it can be written to and read from. But what is the underlying
format? The answer is actually simple: _tosc_ relies on the _pickle_ module
to implement (de)serialization. Objects are wrapped before being pickled so
that when retrieved, they have distributed properties. From this, we can also
deduce that _tosc_ is as portable as _pickle_ itself is.

## Interfaces

```python
class BackendBase
```

  Base class for all backends. In order for a backend to be usable by _tosc_,
  it needs to implement certain features:

  * In addition to storing data, they must maintain the _version_ of the data.
    The version is a numerical value that is unique to a block of data. Note
    that versions don't need to be monotonically increasing, but for simplicity,
    some backends may implement them that way.

  * They must allow atomic replacements of data. In addition, when modifying the
    data, the version that identifies the new data must also be atomically set.

  * The backend must provide an interface analogous to 'compare-and-set'. This
    interface must take an expected version and set the new data only if there
    is a match.

  * Getting the data must also retrieve the version, atomically.

```python
  def read (self) -> Tuple[int, Union[byte, bytearray, memoryview]]
```

  Returns a tuple of version and data blob. The data itself may come in
  different formats, but it must always be pickle-able.

```python
  def write (self, new) -> int
```

  Atomically replaces the stored data with the new object. Returns the new
  version corresponding to the new data.

```python
  def try_write (self, new, expected: Optional[int]) -> bool
```

  Compare the current version with `expected`, and if they match, replace the
  stored data with `new`. If `expected` is None, this is meant to be that
  the backend should expect that no data is being stored. Returns True on
  success, False otherwise.

```python
  def target_wait (self)
```

  Wait for changes on the backend. Returns True if there were any.

  This method is called from a separate thread. As the manager is running,
  it may receive notifications indicating that changes were made. Upon
  receiving such a notice, it will refresh the objects that it manages
  once it's convenient (i.e: Once no transactions are in flight).

```python
class InprocBackend
```

  Implements an in-process backend for a Manager. Instances of this class are
  only useful to share data between threads of the same process.

```python
class FileBackend (file_path, lock_path = None)
```

  Implements a file-based backend. Data is stored in the file at `file_path`.
  The `lock_path` argument is optional and indicates the path for the lock that
  is used to synchronize access across the different process in the distributed
  system.

```python
class CephBackend (client, key, mon_host, pool_name obj_name, max_retries = 100)
```

  Backend based on Ceph, more specifically RADOS objects. Instances of this
  class store all the data in a single object. The constructor parameters
  are as follows:

  * client: Client name, without the 'admin.' bit.
  * key: The cephx key used by the client.
  * mon_host: A comma-separated string of monitor addresses.
  * pool_name: The name of the pool where the object is stored.
  * obj_name: The name of the object where the data will be stored.
  * max_retries: This backend may need to loop a few times when reading the
                 data, or when implementing the `try_write` method. In roder
                 to avoid indefinite starvation, these will only be retried
                 for `max_retries` times.

```python
class Manager (backend)
```

  Returns a manager that is in charge of handling distributed objects stored
  in a backend.

```python
  def is_linked (self, obj) -> bool
```

  Check whether a distributed object is still being stored in the backend. An
  object may be in a `detached` state if it's removed, for example, by a call
  to `list.remove` if a list is being stored.

```python
  def is_dirty (self, obj) -> bool
```

  Check whether an object is dirty - that is, it has been modified, but the
  changes haven't been applied to yet.

```python
  def transaction (self) -> Transaction
```

  Initiate a transaction. Within the scope of a transaction, external changes
  will not be applied, and mutations done to distributed objects will be
  delayed until the transaction exits.

```python
  def read (self) -> object
```

  Read the currently stored object from the backend. Note that if the manager
  caches the last read object and will return it if it considers that no
  changes have occurred in the meantime.

```python
  def refresh (self) -> object
```

  Force the manager to read the currently stored object from the backend. This
  call bypasses the cache mentioned above.

```python
  def write (self, new: object)
```

  Replace the currently stored object with `new`.

```python
  def try_write (self, new, expected: Option[int]) -> bool
```

  Change the currently stored object, but only if the version matches. See the
  documentation for _BackendBase.try_write_ for more details on the semantics.
  Returns True if successful, False otherwise.

```python
def transactional (manager, retries = None, timeout = None)
```

  Function decorator that makes it so that the decorated function will execute
  within a transaction for the passed manager until the transaction succeeds or
  the number of retries (if not None) is reached, or the timeout (if not None)
  is elapsed. If passed, the parameter `retries` must be a positive integer,
  whereas `timeout` must be an integer or float that indicates the number of
  seconds (from it, a deadline in the future will be computed).
