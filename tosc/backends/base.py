class BaseBackend:
  """
  Base class for backends to inherit from. Backends need to implement a set of
  features in order to be usable by tosc:

  - They have to maintain the version of the data they are storing. This
    version must be a numerical value, but there are no additional constraints
    on it (i.e: it doesn't need to be monotonic). The version itself may
    be stored together with the data or independently of it.

  - The backend must allow atomic replacements of the data it's storing. As a 
    corollary from the above, replacing the data also means that the version
    must be updated atomically.

  - The backend must allow conditional atomic replacements when provided with
    an expected version. This is implemented in the 'try_write' method.

  - The backend must support getting the data _and_ the version atomically.
  """

  def __init__ (self):
    self.unique_id = None

  def set_id (self, unique_id):
    if self.unique_id is not None and unique_id is not None:
      raise ValueError ('cannot modify unique id once set')
    self.unique_id = unique_id

  def read (self):
    """
    Returns a tuple of (VERSION, DATA) from the backend. If no data has
    been stored, this method must return (None, None).
    """
    return NotImplemented

  def write (self, new):
    """
    Atomically replace the data stored in the backend and return the new
    version. The backend may be storing no data when this method is called.
    """
    return NotImplemented

  def try_write (self, new, expected):
    """
    Compare the currently stored version with `expected` and replace the stored
    data with `new` if there's a match. Returns a tuple of (SUCCESS, VERSION),
    indicating whether there was a replacement and the current version.

    Note that `expected` may be 0, in which case it means `expect no data
    to be stored at the call`.
    """
    return NotImplemented

  def target_wait (self):
    """
    Wait for changes on the backend. Return True if there were any.

    This method is called from a separate thread. It's used so that clients
    can be asynchronously notified on changes in the backend so that they
    may see the newly up-to-date data. This method must not wait indefinitely:
    each backend has to select a suitable polling interval and sleep no more
    than that limit. This is done because the thread this method is called on
    has only a weak reference to its parent object and must not hold on to it
    more than necessary.

    The backend is not required to implement precise notifications - Periodic
    polling is a perfectly reasonable choice.
    """
    return NotImplemented
