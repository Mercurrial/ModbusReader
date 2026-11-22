"""Editor-only declarations: do not import this file in a macro."""
class Register:
    addr: int
    type: str
    name: str
    def read(self) -> object: ...
    def write(self, value) -> object: ...
    @property
    def value(self) -> object: ...

def reg(key, dtype=None) -> Register:
    """Register handle: .read(), .write(value), .value (a fresh read), .addr, .type, .name."""
    ...

def read(key, dtype=None) -> object:
    """Read a decoded value before scale/offset. Key: map name, address, or IR/CO/DI address string."""
    ...

def write(key, value, dtype=None) -> object:
    """Write a value before scale/offset; return the supplied value. Respect register access permissions."""
    ...

def read_all() -> dict:
    """Read all codec-backed map entries, including STRING; return {name: value}."""
    ...

def wait(seconds) -> None:
    """Interruptible delay in seconds."""
    ...

def sleep(seconds) -> None:
    """Alias of wait."""
    ...

def record(row=None, **kwargs) -> None:
    """Append a result row: a dict and/or named columns; keyword columns override dict keys."""
    ...

def log(*args) -> None:
    """Log arguments joined with spaces."""
    ...

def print(*args) -> None:
    """Alias of log; sep/end/file are not supported."""
    ...

def now() -> float:
    """Unix time in seconds, not a monotonic clock."""
    ...

def timestamp() -> str:
    """Local time: YYYY-MM-DD HH:MM:SS."""
    ...
