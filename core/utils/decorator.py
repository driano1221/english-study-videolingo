import functools
import os
import time

from rich import print as rprint


def except_handler(error_msg, retry=0, delay=1, default_return=None):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for i in range(retry + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    rprint(f"[red]{error_msg}: {exc}, retry: {i + 1}/{retry}[/red]")
                    if i == retry:
                        if default_return is not None:
                            return default_return
                        raise last_exception
                    time.sleep(delay * (2**i))

        return wrapper

    return decorator


def check_file_exists(file_path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # A zero-byte file is a partial artifact, never a completed stage.
            if os.path.isfile(file_path) and os.path.getsize(file_path) > 0:
                rprint(
                    f"[yellow]File <{file_path}> already exists; "
                    f"skipping <{func.__name__}>.[/yellow]"
                )
                return None
            return func(*args, **kwargs)

        return wrapper

    return decorator


if __name__ == "__main__":
    @except_handler("function execution failed", retry=3, delay=1)
    def test_function():
        raise Exception("test exception")

    test_function()
