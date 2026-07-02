import unittest
from unittest.mock import patch

from ibgateway import IBGateway


class IBGatewayReadinessTests(unittest.TestCase):
    def test_ensure_gateway_does_not_recurse_through_mgr_when_probe_fails(self):
        gateway = IBGateway()

        class DummyMgr:
            def __init__(self):
                self.get_ib_conn_called = False

            def get_ib_conn(self):
                self.get_ib_conn_called = True
                raise AssertionError("manager should not be re-entered")

        mgr = DummyMgr()

        with patch.object(gateway, "start_gateway") as start_gateway_mock, \
             patch.object(gateway, "stop_gateway") as stop_gateway_mock, \
             patch("ibgateway.QuestDBManager.is_port_open", return_value=True), \
             patch("ibgateway.IB") as ib_cls, \
             patch("ibgateway.time.sleep", return_value=None):
            ib_instance = ib_cls.return_value
            ib_instance.connect.side_effect = Exception("boom")

            result = gateway.ensure_gateway(mgr=mgr, timeout=5)

        self.assertFalse(result)
        self.assertFalse(mgr.get_ib_conn_called)
        stop_gateway_mock.assert_called_once()
        start_gateway_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
