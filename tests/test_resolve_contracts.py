import unittest
from types import SimpleNamespace

from ib_insync import FuturesOption, Stock

from utils import resolve_contracts, resolve_option_underlying


class ResolveContractsTests(unittest.TestCase):
    def test_resolve_contracts_uses_per_contract_metadata(self):
        class DummyIB:
            def __init__(self):
                self.calls = []

            def reqContractDetails(self, contract):
                self.calls.append(contract)
                return [SimpleNamespace(contract=SimpleNamespace(
                    localSymbol=contract.symbol,
                    exchange=contract.exchange,
                    currency=contract.currency,
                    multiplier=getattr(contract, "multiplier", None),
                    lastTradeDateOrContractMonth="202612",
                ))]

        ib = DummyIB()
        contracts = [
            {"ric": "ESU6", "exchange": "CME", "sec_type": "FUT", "currency": "USD", "multiplier": "50"},
            {"ric": "AAPL", "exchange": "SMART", "sec_type": "STK", "currency": "USD", "multiplier": "1"},
        ]

        results = resolve_contracts(ib, contracts)

        self.assertEqual(len(results), 2)
        self.assertEqual(ib.calls[0].exchange, "CME")
        self.assertEqual(ib.calls[1].exchange, "SMART")
        self.assertEqual(ib.calls[0].symbol, "ES")
        self.assertIsInstance(ib.calls[1], Stock)
        self.assertEqual(results[0][1], "ES")
        self.assertEqual(results[1][1], "AAPL")

    def test_resolve_option_underlying_returns_futures_ric(self):
        self.assertEqual(resolve_option_underlying("ESU62000C"), "ESU6")
        self.assertEqual(resolve_option_underlying("esu62000p"), "ESU6")

    def test_resolve_contracts_supports_options(self):
        class DummyIB:
            def __init__(self):
                self.calls = []

            def reqContractDetails(self, contract):
                self.calls.append(contract)
                return [SimpleNamespace(contract=SimpleNamespace(
                    localSymbol=contract.symbol,
                    exchange=contract.exchange,
                    currency=contract.currency,
                    multiplier=getattr(contract, "multiplier", None),
                    lastTradeDateOrContractMonth=getattr(contract, "lastTradeDateOrContractMonth", ""),
                ))]

        ib = DummyIB()
        contracts = [{"ric": "ESU62000C", "exchange": "CME", "sec_type": "OPT", "currency": "USD", "multiplier": "50"}]

        results = resolve_contracts(ib, contracts)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(ib.calls[0], FuturesOption)
        self.assertEqual(ib.calls[0].symbol, "ES")
        self.assertEqual(ib.calls[0].strike, 2000.0)
        self.assertEqual(ib.calls[0].right, "C")
        self.assertEqual(results[0][1], "ES")


if __name__ == "__main__":
    unittest.main()
