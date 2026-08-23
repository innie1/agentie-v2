import unittest
from unittest.mock import patch

from agentie.core import company_computer_idle as idle


class CompanyComputerIdleRegressionTests(unittest.TestCase):
    def test_stale_agent_lease_is_released_then_suspended(self):
        current={"state":"AGENT_CONTROL","controller_type":"agent","last_activity":100.0}
        with patch.object(idle.computer,"_row",return_value=current), patch.object(idle.computer,"IDLE_SECONDS",60), patch.object(idle.computer,"release_control",return_value={}) as release, patch.object(idle.computer,"suspend",return_value={}) as suspend:
            result=idle.run_idle_cycle(now=200.0)
        self.assertEqual(result,"suspended")
        release.assert_called_once_with()
        suspend.assert_called_once_with()

    def test_active_agent_lease_is_not_reclaimed(self):
        current={"state":"AGENT_CONTROL","controller_type":"agent","last_activity":180.0}
        with patch.object(idle.computer,"_row",return_value=current), patch.object(idle.computer,"IDLE_SECONDS",60), patch.object(idle.computer,"release_control") as release, patch.object(idle.computer,"suspend") as suspend:
            result=idle.run_idle_cycle(now=200.0)
        self.assertIsNone(result);release.assert_not_called();suspend.assert_not_called()

    def test_user_control_is_never_automatically_reclaimed(self):
        current={"state":"USER_CONTROL","controller_type":"user","last_activity":1.0}
        with patch.object(idle.computer,"_row",return_value=current), patch.object(idle.computer,"IDLE_SECONDS",60), patch.object(idle.computer,"release_control") as release, patch.object(idle.computer,"suspend") as suspend:
            result=idle.run_idle_cycle(now=9999.0)
        self.assertIsNone(result);release.assert_not_called();suspend.assert_not_called()

    def test_user_required_takeover_is_never_suspended(self):
        current={"state":"USER_REQUIRED","controller_type":"agent","last_activity":1.0}
        with patch.object(idle.computer,"_row",return_value=current), patch.object(idle.computer,"IDLE_SECONDS",60), patch.object(idle.computer,"suspend") as suspend:
            result=idle.run_idle_cycle(now=9999.0)
        self.assertIsNone(result);suspend.assert_not_called()


if __name__=="__main__":unittest.main()
