## *tosc* --- Easy distributed data structures for Python

This library implements seamless distributed data structures for Python.
The aim is to let users write their programs in a normal, Pythonic fashion,
while at the same maintaining all the constraints of a distributed system -
i.e: Data is always consistent across all the nodes, and changes are only
applied transactionally and atomically.

## Managers

The **Manager** is the central component in TOSC. It's responsible for:

- Maintaining references to distributed objects
- Handling (de)serialization using pickle
- Tracking versions to detect conflicts
- Running a background watcher thread to detect remote changes
- Orchestrating transactions

Every distributed application using TOSC starts by creating a Manager:

```python

import tosc

# Instantiate a manager with a backend
manager = tosc.Manager(tosc.FileBackend('/tmp/some-file'))

# Write an object to the manager.
manager.write(some_object(...))

# Retrieve the object that was written.
obj = manager.read()

# The object can now be manipulated in any way. The changes made
# to it will be applied transactionally, and any user holding
# references will be notified of said changes.
```

## Backends

A **Backend** is a pluggable storage layer that provides atomic operations. All backends must implement:

- `read()`: Atomically retrieve data and its version
- `write(data)`: Atomically store data, returning new version
- `try_write(data, expected_version)`: Conditional write (compare-and-swap)
- `target_wait()`: Block until backend data changes (for the watcher thread)

As of the time of this writing, _tosc_ supports 3 backends:

* In-process backend (_tosc.InprocBackend_): This backend is only usable to
  share data across threads in the same process. Although not truly distributed,
  it's still useful if the user needs the properties of a distributed system,
  such as the possibility of applying changes atomically without the need for
  explicit threading primitives such as locks.

* File-based backend (_tosc.FileBackend_): This backend stores the data in
  a regular file. Changes are made atomic by virtue of filesystem semantics.
  The file used for the backing can be either local, or remote (as in NFS or
  Ceph-FS). In the latter case, this backend can be used to share data in a
  truly distributed way.

* Ceph-backend (_tosc.CephBackend_): The most scalable backend available, this
  one is only optionally built, in the presence of the _librbd_ and
  _librados_ libraries for Python.

## Versioning

Every piece of data stored through a Manager has an associated **version** (an integer). When data changes:

1. The version increments
2. The new version is stored atomically with the data
3. Managers track versions to detect when data changes externally

This versioning enables:

- **Optimistic locking**: Detect conflicts without holding locks
- **Conditional updates**: Only apply changes if no one else modified the data
- **Change detection**: Know when to refresh cached objects

## Transactions

A **Transaction** is a context manager that:

- Prevents external changes from being applied during its scope
- Buffers all mutations to distributed objects
- Commits changes atomically on exit
- Rolls back on failure or conflict

Transactions use optimistic locking: they succeed only if no other transaction modified the data concurrently.

```python
with manager.transaction() as tr:
    # All mutations here apply atomically
    obj['key'] = 'value'
```

## Distributed Types

When you write a Python object through a Manager, TOSC wraps it in a distributed type:

| Python Type | TOSC Wrapper | Description |
|-------------|--------------|-------------|
| `list` | `DList` | Distributed list |
| `dict` | `DDict` | Distributed dictionary |
| `set` | `DSet` | Distributed set |
| `bytearray` | `DByteArray` | Distributed byte array |
| Custom objects | `DAny` | Generic wrapper for objects with `__dict__` or `__slots__` |

These wrappers intercept mutations and coordinate with the Manager to ensure consistency.

## About distributed semantics and transactions

If we hold a distributed object and another process makes changes to it, the
Manager will _eventually_ be notified and apply said changes, thereby providing
an up-to-date view of the managed objects. This can lead to surprises as objects
change underneath us without notice. In order to avoid these kinds of surprises,
we can make use of _transactions_.

For example:

```python
manager = tosc.Manager(backend)
data = manager.read()

with manager.transaction():
    data['key1'] = 'value1'
    data['list'].append(42)
    # All changes are commited atomically here
```

As long as a transaction is ongoing, the manager will not apply any changes
made by external processes. If, on the other hand, _we_ mutate the state of
any distributed object, then once the transaction finishes, the manager will
see to it that the changes are propagated:

```python
obj = manager.read()

with manager.transaction() as tr:
  mutate_object(obj)
  # once the transaction ends, the changes to `obj` will be sent through
  # the backend and to the other nodes in the system.
```

Note also that transactions may be _implicit_:

```python
obj.write([1, 2, 3])

lst = obj.read()
lst.append(4)   # This is an implicit transaction and thus may fail (see below)
```

Transactions can be nested. Only the outermost transaction commits changes:

```python
with manager.transaction():
    data['a'] = 1

    with manager.transaction():  # Nested
        data['b'] = 2
    # Inner transaction doesn't commit yet

    data['c'] = 3
# All changes commit here atomically
```

### Handling Transaction Failures

Transactions can fail if another process commits changes first:

```python
data = manager.read()

try:
    with manager.transaction():
        data['counter'] += 1
except tosc.TransactionError:
    print("Transaction failed - another process modified the data")
```

### The @transactional Decorator

For automatic retry on conflicts, use the `@transactional` decorator:

```python
@tosc.transactional(manager)
def increment_counter(data):
    data['counter'] += 1

data = manager.read()
increment_counter(data)  # Retries automatically on conflict
```

**With retry limit**:

```python
@tosc.transactional(manager, retries=10)
def risky_operation(data):
    # Will retry up to 10 times
    data['value'] = expensive_computation()
```

**With timeout**:

```python
@tosc.transactional(manager, timeout=5.0)
def timed_operation(data):
    # Will retry for up to 5 seconds
    data['timestamp'] = time.time()
```

**Both can be used at the same time**:

```python
@tosc.transactional(manager, retries=20, timeout=10.0)
def safe_operation(data):
    # Retries up to 20 times or 10 seconds, whichever comes first
    update_data(data)
```

### Transaction Exceptions

- `TransactionError`: Base exception for transaction failures
- `TransactionRetryError`: Raised when retry limit is reached
- `TransactionTimeoutError`: Raised when timeout is exceeded

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
    that versions must be incremental, but they don't need to be monotonic.    

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

  Implements an in-process backend for a Manager. Although not truly
  distributed, this backend is still useful to share complex data atomically
  across multiple threads. It can also be used for testing and to get a better
  understanding of distributed semantics and constraints.

```python
class FileBackend (file_path, lock_path = None)
```

  Implements a file-based backend. Data is stored in the file at `file_path`.
  The `lock_path` argument is optional and indicates the path for the lock that
  is used to synchronize access across the different process in the distributed
  system.

  The features of this backend depend largely on the filesystem being used. If
  the filesystem is only backed by memory (as is the case of files in /dev/shm),
  then the writes will not be persistent. On the other hand, if the filesystem
  if network-based (as with NFS or CephFS), then the backend can be used across
  nodes in different machines.

  Typically, this backend would be used to synchronize and share data with
  unrelated processes in the same machine. It's specially suited to share
  configuration and apply updates seamlessly.

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

  This backend is exceptionally suited for large-scale distributed systems,
  and for production environments where a Ceph cluster is already up and
  running. Applications that require high-availability can make good use of
  this backend as well.

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

  Transactions are context-managers.

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
  def snapshot (self) -> object
```

  Returns a snapshot of the currently stored object. Note that the returned
  object is no longer distributed and will be of the original type.

```python
def transactional (manager, retries = None, timeout = None)
```

  Function decorator that makes it so that the decorated function will execute
  within a transaction for the passed manager until the transaction succeeds or
  the number of retries (if not None) is reached, or the timeout (if not None)
  is elapsed. If passed, the parameter `retries` must be a positive integer,
  whereas `timeout` must be an integer or float that indicates the number of
  seconds (from it, a deadline in the future will be computed).
