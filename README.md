# TOSC - Transparent Distributed Data Structures for Python

TOSC enables developers to write distributed applications in Python using familiar data structures (lists, dicts, sets, etc.) that automatically synchronize across multiple processes or nodes. No explicit locking, no manual serialization, just pure Pythonic code with distributed semantics.

## Features

- **Transparent Distribution**: Write code as if working with local objects, while TOSC handles distributed consistency automatically
- **Transactional Semantics**: All changes apply atomically with optimistic locking and automatic conflict resolution
- **Multiple Backends**: Choose from in-process (threading), file-based (local/NFS/CephFS), or Ceph RADOS backends
- **Automatic Change Detection**: Mutations to distributed objects are tracked and propagated without manual intervention
- **Background Synchronization**: A watcher thread keeps objects up-to-date across all nodes
- **Conflict Resolution**: Built-in compare-and-swap ensures consistency when multiple nodes modify data concurrently

## Quick Start

### Install from source

```bash
python3 setup.py install
```

### (Optional) Install with support for Ceph backend

For this backend to be installed, you'll need the python3 bindings for librados and librbd:

```bash
# On Debian-based systems:
apt install python3-rados python3-rbd
```

### Basic Usage

```python
import tosc

# Create a manager with a file-based backend
manager = tosc.Manager(tosc.FileBackend('/tmp/shared-data'))

# Write any Python object
manager.write({'users': [], 'config': {'debug': False}})

# Read the distributed object
data = manager.read()

# Mutate within a transaction - changes apply atomically
with manager.transaction():
    data['users'].append({'name': 'Alice', 'id': 1})
    data['config']['debug'] = True
# Changes are now visible to all processes sharing this backend
```

### Automatic retry with Conflicts

When multiple processes modify data simultaneously, TOSC uses optimistic locking. Use the `@transactional` decorator to automatically retry on conflicts:

```python
@tosc.transactional(manager)
def add_user(data, username):
    # This function will retry automatically if another process
    # commits changes at the same time
    users = data['users']
    for user in users:
        if user.get('name') == username:
          break
    else:
        # Add username if not already present.
        users.append({'name': username, 'id': len(users) + 1}) 

data = manager.read()
add_user(data, 'Bob')  # Retries automatically on conflict
```

## Core Concepts

### Manager
The central orchestrator that maintains consistency, handles serialization, and manages the lifecycle of distributed objects.

### Backends
Pluggable storage layers that provide atomic read/write/compare-and-swap operations:

- **InprocBackend**: Thread-safe, in-memory sharing within a single process
- **FileBackend**: File-based storage with atomic operations (works over NFS, CephFS)
- **CephBackend**: Scalable backend using Ceph RADOS objects

### Transactions
A context manager that batches mutations and applies them atomically. During a transaction:
- External changes are blocked from being applied
- All mutations are buffered
- On exit, changes commit atomically or roll back on conflict

### Distributed Types
Python types are automatically wrapped when written through a Manager:
- `list` → `DList`
- `dict` → `DDict`
- `set` → `DSet`
- `bytearray` → `DByteArray`
- Custom objects → `DAny`

These wrappers provide the same interface as their standard counterparts while adding distributed semantics.

## Architecture Highlights

- **Optimistic Locking**: Uses version numbers for conflict detection
- **Copy-on-Write**: Mutations create copies to avoid affecting concurrent readers
- **Background Watcher**: Separate thread monitors backend for changes
- **Pickle-Based Serialization**: Compatible with any pickle-able Python object

## Use Cases

- **Distributed Configuration**: Share configuration across multiple service instances
- **Coordinated State**: Maintain shared state in distributed applications
- **Multi-Process Coordination**: Coordinate work between processes without explicit IPC
- **Distributed Caching**: Share cache state across nodes
- **Cluster Metadata**: Store and synchronize cluster-wide metadata

## Example: Distributed Counter

```python
import tosc
from threading import Thread

# File-based backend for cross-process sharing
manager = tosc.Manager(tosc.FileBackend('/tmp/counter'))
manager.write({'count': 0})

@tosc.transactional(manager)
def increment():
    data = manager.read()
    data['count'] += 1

# Run from multiple processes/threads - each increment is atomic
threads = [Thread(target=increment) for _ in range(100)]
for t in threads:
    t.start()
for t in threads:
    t.join()

print(manager.read()['count'])  # Guaranteed to be 100
```

## Further information

Please consult [the manual](./docs/manual.md) for the API reference and interface documentation.

## Requirements

- Python 3.x
- `filelock` (automatically installed)
- Optional: Ceph libraries (`librbd`, `librados`) for CephBackend

## License

TOSC is released under the [GNU General Public License v3.0](LICENSE).

## Authors

- Luciano Lo Giudice
- Agustina Arzille

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests on [GitHub](https://github.com/lmlg/tosc/).

## Support

For questions, issues, or feature requests, please use the [GitHub issue tracker](https://github.com/lmlg/tosc/issues).
