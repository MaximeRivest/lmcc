"""The Python reference behind the driver protocol (kernel §9).

One case per line on stdin, one answer per line on stdout. It exists so the
protocol stays tested while Python is the only implementation, and as the
template a driver in another language follows:

    python runner.py --driver 'python python_driver.py'
"""

import json
import sys

from runner import PythonDriver


def main() -> None:
    driver = PythonDriver()
    for line in sys.stdin:
        if line.strip():
            print(json.dumps(driver.run(json.loads(line)), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
