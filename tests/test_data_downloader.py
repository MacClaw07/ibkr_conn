import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

if "ib_async" not in sys.modules:
    ib_async = types.ModuleType("ib_async")

    class Contract:  # noqa: D401
        pass

    class Future(Contract):
        pass

    class FuturesOption(Contract):
        pass

    class Stock(Contract):
        pass

    class BarData:  # noqa: D401
        pass

    class IB:  # noqa: D401
        pass

    class Ticker:  # noqa: D401
        pass

    ib_async.Contract = Contract
    ib_async.Future = Future
    ib_async.FuturesOption = FuturesOption
    ib_async.Stock = Stock
    ib_async.BarData = BarData
    ib_async.IB = IB
    ib_async.Ticker = Ticker
    sys.modules["ib_async"] = ib_async

from data_downloader import DataDownloader


class DummyManager:
    def __init__(self, ib=None, qdb=None):
        self.ib = ib
        self.qdb = qdb
        self.error_count = 0

    def get_ib_conn(self):
        return self.ib

    def get_questdb(self):
        return self.qdb

    def on_error(self):
        self.error_count += 1


class DataDownloaderTests(unittest.TestCase):
    def test_download_bars_writes_to_questdb_from_downloaded_bars(self):
        manager = DummyManager(ib=object(), qdb=SimpleNamespace(write_bars=lambda bars, label, expiry: 1))
        downloader = DataDownloader(manager)
        bars = [SimpleNamespace(date="2024-01-01")]

        with patch.object(
            downloader,
            "_do_bars_download",
            return_value=(bars, "AAPL", "2024-01-01", "2024-01-01", "2024-01-02"),
        ) as mocked_download:
            args = SimpleNamespace(
                format="questdb",
                output=None,
                bar_size="1 day",
                what_to_show="TRADES",
                use_rth=False,
                all_hours=False,
                date="2024-01-01:2024-01-02",
            )

            downloader.download_bars(
                date=args.date,
                bar_size=args.bar_size,
                what_to_show=args.what_to_show,
                use_rth=args.use_rth,
                all_hours=args.all_hours,
            )

        mocked_download.assert_called_once_with(manager.ib, args)


if __name__ == "__main__":
    unittest.main()
