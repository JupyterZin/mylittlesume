import threading
import time

from talos.connectors.google_lock import serialized


def test_serialized_methods_never_overlap():
    @serialized
    class Api:
        def __init__(self):
            self.active = 0
            self.max_active = 0

        def call(self):
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            time.sleep(0.01)
            self.active -= 1
            return "ok"

    api = Api()
    threads = [threading.Thread(target=api.call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert api.max_active == 1 and api.call() == "ok"


def test_google_connectors_are_serialized():
    from talos.connectors.calendar import GoogleCalendar
    from talos.connectors.drive import GoogleDrive
    from talos.connectors.gmail import GoogleGmail

    for cls in (GoogleGmail, GoogleCalendar, GoogleDrive):
        public = [n for n in vars(cls) if not n.startswith("_") and callable(vars(cls)[n])]
        assert public and all(hasattr(vars(cls)[n], "__wrapped__") for n in public), cls
