import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agentie.core import activity_feed,agent_registry,automation_events,routine_engine,team_orchestrator,workflow_skill_runtime
from agentie.tools import approval_tools


class ActivityExternalAutomationRegressionTests(unittest.TestCase):
    def test_activity_feed_surfaces_external_event_and_replan_metadata(self):
        with tempfile.TemporaryDirectory() as raw:
            root=Path(raw)
            patches=[
                patch.object(agent_registry,'WORKSPACE',root),patch.object(agent_registry,'AGENTS_FILE',root/'agents.json'),
                patch.object(automation_events,'WORKSPACE',root),patch.object(automation_events,'EVENTS',root/'automation_events.json'),
                patch.object(team_orchestrator,'WORKSPACE',root),patch.object(team_orchestrator,'TEAM_FILE',root/'team_jobs.json'),
                patch.object(routine_engine,'WORKSPACE',root),patch.object(routine_engine,'ROUTINES',root/'routines.json'),patch.object(routine_engine,'RUNS',root/'routine_runs.json'),
                patch.object(workflow_skill_runtime,'WORKSPACE',root),patch.object(workflow_skill_runtime,'RUNS',root/'skill_runs.json'),patch.object(approval_tools,'STORE',root/'approvals.json'),
                patch.object(activity_feed,'recent_traces',return_value=[]),
            ]
            for p in patches:p.start()
            try:
                agent=agent_registry.create_agent('Ada','Operations owner')['agent'];job=team_orchestrator.create_team_job('Handle external lead',[agent]);team_orchestrator._mutate(job['id'],lambda j:j.update(replan_count=1,recovery_history=[{'from_agent':'Old','to_agent':'Ada','classification':'transient'}]));automation_events.publish_event('crm.lead.created',{'agent_id':agent['id'],'agent_name':agent['name'],'message':'New lead'},source='webhook')
                items=activity_feed.activity_items(agent_id=agent['id'],limit=20);event=next(x for x in items if x['kind']=='automation_event');collab=next(x for x in items if x['kind']=='collaboration')
                self.assertEqual(event['metadata']['event_type'],'crm.lead.created');self.assertEqual(event['metadata']['source'],'webhook');self.assertEqual(collab['metadata']['replan_count'],1);self.assertTrue(collab['metadata']['recovery_history'])
            finally:
                for p in reversed(patches):p.stop()


if __name__=='__main__':unittest.main()
