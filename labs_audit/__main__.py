import sys

from .adapters.inbound.cli import main

RUN_AS_ENTRYPOINT = __name__ == "__main__"

if RUN_AS_ENTRYPOINT:
    sys.exit(main())
