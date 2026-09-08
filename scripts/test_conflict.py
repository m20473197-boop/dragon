"""Graceful handling of telegram.error.Conflict (duplicate bot instance)."""
from __future__ import annotations

import logging
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DRAGON_BOT_TOKEN", "test:token")
os.environ["DRAGON_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "conflict.db")

import asyncio  # noqa: E402

from telegram.error import Conflict, NetworkError, TimedOut  # noqa: E402

from handlers import errors as err  # noqa: E402

RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append(bool(cond))
    print(("✅" if cond else "❌"), name, extra if not cond else "")


class Capture(logging.Handler):
    """Collect records emitted on a logger."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)

    def messages(self, level=logging.ERROR):
        return [r.getMessage() for r in self.records if r.levelno >= level]


class FakeContext:
    def __init__(self, error):
        self.error = error
        self.bot_data = {}


class FakeChat:
    def __init__(self):
        self.sent = []

    async def send_message(self, text, **kw):
        self.sent.append(text)


class FakeMessage:
    def __init__(self):
        self.chat = FakeChat()


class FakeUpdate:
    def __init__(self):
        self.effective_message = FakeMessage()


def main():
    # --- 1. the handler recognises Conflict --------------------------------
    err.reset_conflict_state()
    cap = Capture()
    err.logger.addHandler(cap)
    err.logger.setLevel(logging.DEBUG)

    update = FakeUpdate()
    asyncio.run(err.on_error(update, FakeContext(Conflict("terminated by other getUpdates request"))))
    errs = cap.messages()
    check("a Conflict is logged", len(errs) == 1, errs)
    check(
        "the message explains a duplicate instance",
        "another instance" in errs[0].lower() and "only one" in errs[0].lower(),
        errs[0] if errs else "",
    )
    check(
        "the message says how to fix it",
        "webhook" in errs[0].lower() and "restart" in errs[0].lower(),
    )
    check("no traceback is dumped for a Conflict", cap.records[0].exc_info is None)
    check("no user-facing message is sent", update.effective_message.chat.sent == [])

    # --- 2. no endless log spam --------------------------------------------
    cap.records.clear()
    for _ in range(500):
        asyncio.run(err.on_error(update, FakeContext(Conflict("terminated by other getUpdates request"))))
    check(
        "500 further conflicts produce no new error lines",
        len(cap.messages()) == 0,
        cap.messages(),
    )
    check(
        "suppressed conflicts are still counted at debug level",
        len([r for r in cap.records if r.levelno == logging.DEBUG]) == 500,
    )
    check("occurrences are counted", int(err._conflict_state["count"]) == 501)

    # --- 3. a reminder is logged again after the interval -------------------
    cap.records.clear()
    logged = err._handle_conflict(
        now=err._conflict_state["last_log"] + err.CONFLICT_LOG_INTERVAL_SECONDS + 1
    )
    check("a reminder is logged after the interval", logged and len(cap.messages()) == 1)
    check(
        "the reminder reports how many were suppressed",
        "repeated" in cap.messages()[0].lower(),
        cap.messages(),
    )

    # --- 4. other errors are unaffected -------------------------------------
    err.reset_conflict_state()
    cap.records.clear()
    asyncio.run(err.on_error(update, FakeContext(TimedOut())))
    check("timeouts still logged as warnings",
          any(r.levelno == logging.WARNING for r in cap.records))
    cap.records.clear()
    asyncio.run(err.on_error(update, FakeContext(ValueError("real bug"))))
    check("real bugs still logged with a traceback",
          any(r.levelno >= logging.ERROR and r.exc_info for r in cap.records))
    check("real bugs still notify the user",
          update.effective_message.chat.sent != [])
    check("a real bug does not touch the conflict counter",
          int(err._conflict_state["count"]) == 0)

    err.logger.removeHandler(cap)

    # --- 5. the log filter collapses PTB's own polling tracebacks -----------
    err.reset_conflict_state()
    err.install_conflict_filter()
    err.install_conflict_filter()  # idempotent

    updater_logger = logging.getLogger("telegram.ext.Updater")
    filters = [f for f in updater_logger.filters if isinstance(f, err.ConflictLogFilter)]
    check("filter installed exactly once", len(filters) == 1, len(filters))

    ucap = Capture()
    updater_logger.addHandler(ucap)
    updater_logger.setLevel(logging.DEBUG)
    ecap = Capture()
    err.logger.addHandler(ecap)

    exc = Conflict("terminated by other getUpdates request")
    for _ in range(200):
        try:
            raise exc
        except Conflict:
            updater_logger.exception("Exception happened while polling for updates.")

    check(
        "PTB's 200 polling tracebacks are swallowed",
        ucap.messages() == [],
        ucap.messages()[:1],
    )
    check(
        "they are replaced by one clear explanation",
        len(ecap.messages()) == 1 and "another instance" in ecap.messages()[0].lower(),
        ecap.messages(),
    )

    # non-conflict records must pass through untouched
    ucap.records.clear()
    try:
        raise NetworkError("some other problem")
    except NetworkError:
        updater_logger.exception("Exception happened while polling for updates.")
    check("unrelated polling errors still get through", len(ucap.messages()) == 1)

    updater_logger.removeHandler(ucap)
    err.logger.removeHandler(ecap)

    # --- 6. startup is unchanged --------------------------------------------
    import bot as bot_module  # noqa: E402

    check("bot module still exposes main()", callable(bot_module.main))
    check(
        "bot installs the filter at import time",
        any(
            isinstance(f, err.ConflictLogFilter)
            for f in logging.getLogger("telegram.ext.Updater").filters
        ),
    )

    print()
    passed = sum(RESULTS)
    print(f"{passed}/{len(RESULTS)} checks passed")
    if passed == len(RESULTS):
        print("All conflict-handling tests passed ✅")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
